"""Right-sizing and health rules.

Each rule inspects one workload and returns zero or more recommendations.
Cost rules (reclaiming over-provisioned requests) carry a dollar figure;
reliability rules (throttling, OOM, JVM mismatch, under-provisioning) carry
zero savings and exist to stop right-sizing from causing an incident.
"""
from __future__ import annotations

from .models import Category, NodeCost, Recommendation, Runtime, Severity, Workload
from .policy import Policy


def _sev(monthly_savings: float) -> Severity:
    if monthly_savings >= 200:
        return Severity.HIGH
    if monthly_savings >= 50:
        return Severity.MEDIUM
    return Severity.LOW


def rightsize_cpu(w: Workload, p: Policy, cost: NodeCost) -> Recommendation | None:
    """Reclaim over-requested CPU, or raise a starved request."""
    target = p.cpu_target_m(w.cpu_p95_m, w.vpa_cpu_target_m)

    # under-provisioned: sustained usage at/over the request -> reliability
    if w.cpu_p95_m >= w.cpu_request_m:
        return Recommendation(
            w.id, w.project, "cpu_request", "raise",
            f"cpu request {w.cpu_request_m}m -> {target}m",
            Category.RELIABILITY, Severity.HIGH, 0.0,
            f"p95 CPU {w.cpu_p95_m:.0f}m ≥ request {w.cpu_request_m}m — the pod is "
            f"CPU-starved and will be first evicted under pressure",
            ["cpu", "under-provisioned"],
        )

    reclaim_m = w.cpu_request_m - target
    if reclaim_m < p.min_cpu_reclaim_m or w.cpu_request_m < target * p.over_request_ratio:
        return None
    savings = (reclaim_m / 1000.0) * cost.cpu_core_month * w.replicas
    return Recommendation(
        w.id, w.project, "cpu_request", "downsize",
        f"cpu request {w.cpu_request_m}m -> {target}m  (×{w.replicas} replicas)",
        Category.COST, _sev(savings), savings,
        f"p95 CPU {w.cpu_p95_m:.0f}m"
        + (f", Goldilocks/VPA target {w.vpa_cpu_target_m}m" if w.vpa_cpu_target_m else "")
        + f" — request of {w.cpu_request_m}m reserves node capacity nothing uses",
        ["cpu", "rightsizing"],
    )


def rightsize_memory(w: Workload, p: Policy, cost: NodeCost) -> Recommendation | None:
    """Reclaim over-requested memory — but never below the peak/startup/JVM floor."""
    target = p.mem_target_mi(w)

    # under-provisioned: working set near/over request
    if w.mem_peak_mi >= w.mem_request_mi:
        return Recommendation(
            w.id, w.project, "mem_request", "raise",
            f"mem request {w.mem_request_mi}Mi -> {target}Mi",
            Category.RELIABILITY, Severity.HIGH, 0.0,
            f"working-set peak {w.mem_peak_mi:.0f}Mi ≥ request {w.mem_request_mi}Mi — "
            f"memory is non-compressible, so this risks eviction/OOM",
            ["memory", "under-provisioned"],
        )

    reclaim_mi = w.mem_request_mi - target
    if reclaim_mi < p.min_mem_reclaim_mi:
        return None
    savings = (reclaim_mi / 1024.0) * cost.mem_gib_month * w.replicas
    floor_note = ""
    if w.runtime is Runtime.JVM and w.heap_max_mi:
        floor_note = f" (floored at -Xmx {w.heap_max_mi}Mi + non-heap + overhead)"
    return Recommendation(
        w.id, w.project, "mem_request", "downsize",
        f"mem request {w.mem_request_mi}Mi -> {target}Mi  (×{w.replicas} replicas)",
        Category.COST, _sev(savings), savings,
        f"sized to working-set peak {w.mem_peak_mi:.0f}Mi / startup peak "
        f"{w.startup_mem_peak_mi:.0f}Mi{floor_note} — request had unused slack",
        ["memory", "rightsizing"],
    )


def check_cpu_throttling(w: Workload, p: Policy) -> Recommendation | None:
    """A CPU limit set too tight throttles the app even when average CPU is low."""
    if w.cpu_limit_m and w.cpu_throttle_pct > p.cpu_throttle_flag:
        return Recommendation(
            w.id, w.project, "cpu_limit", "raise",
            f"cpu limit {w.cpu_limit_m}m is throttling {w.cpu_throttle_pct:.0%} of periods",
            Category.RELIABILITY, Severity.HIGH, 0.0,
            f"{w.cpu_throttle_pct:.0%} of CFS periods throttled at a {w.cpu_limit_m}m limit — "
            f"raise the limit or drop it entirely; latency is being clipped invisibly",
            ["cpu", "throttling"],
        )
    return None


def check_startup_cpu_limit(w: Workload) -> Recommendation | None:
    """JVM startup spikes CPU; a limit below the startup peak means slow, flaky boots."""
    if w.cpu_limit_m and w.startup_cpu_peak_m > w.cpu_limit_m:
        return Recommendation(
            w.id, w.project, "cpu_limit", "raise",
            f"startup peak {w.startup_cpu_peak_m:.0f}m exceeds cpu limit {w.cpu_limit_m}m",
            Category.RELIABILITY, Severity.MEDIUM, 0.0,
            f"the app needs ~{w.startup_cpu_peak_m:.0f}m during JVM warm-up but the limit "
            f"caps it at {w.cpu_limit_m}m — startup gets throttled, readiness probes flake",
            ["cpu", "startup", "jvm"],
        )
    return None


def check_oom(w: Workload, p: Policy) -> Recommendation | None:
    if w.mem_limit_mi and (w.oom_killed > 0 or w.mem_peak_mi > w.mem_limit_mi * p.mem_peak_limit_ratio):
        why = (f"{w.oom_killed} OOM-kill(s) observed" if w.oom_killed
               else f"peak {w.mem_peak_mi:.0f}Mi is >{p.mem_peak_limit_ratio:.0%} of the "
                    f"{w.mem_limit_mi}Mi limit")
        return Recommendation(
            w.id, w.project, "mem_limit", "raise",
            f"mem limit {w.mem_limit_mi}Mi too tight",
            Category.RELIABILITY, Severity.HIGH, 0.0,
            f"{why} — raise the memory limit to restore headroom before it OOM-kills in prod",
            ["memory", "oom"],
        )
    return None


def check_jvm_heap(w: Workload, p: Policy) -> Recommendation | None:
    """Container memory limit must clear -Xmx + non-heap + overhead, or the JVM
    OOMs the container at exactly the wrong moment."""
    if w.runtime is not Runtime.JVM or not w.heap_max_mi or not w.mem_limit_mi:
        return None
    needed = w.heap_max_mi + w.nonheap_used_mi + p.jvm_overhead_mi
    if needed > w.mem_limit_mi:
        return Recommendation(
            w.id, w.project, "jvm", "tune",
            f"-Xmx {w.heap_max_mi}Mi + non-heap {w.nonheap_used_mi:.0f}Mi + overhead "
            f"> mem limit {w.mem_limit_mi}Mi",
            Category.RELIABILITY, Severity.HIGH, 0.0,
            f"heap ceiling plus non-heap needs ~{needed:.0f}Mi but the container limit is "
            f"{w.mem_limit_mi}Mi — lower -Xmx (or use -XX:MaxRAMPercentage) or raise the limit",
            ["jvm", "heap", "oom"],
        )
    return None


def check_threads(w: Workload, p: Policy) -> Recommendation | None:
    if w.thread_ceiling and w.threads_peak > w.thread_ceiling * p.thread_ceiling_ratio:
        return Recommendation(
            w.id, w.project, "threads", "tune",
            f"threads peak {w.threads_peak} vs ceiling {w.thread_ceiling}",
            Category.RELIABILITY, Severity.MEDIUM, 0.0,
            f"live threads peaked at {w.threads_peak}, >{p.thread_ceiling_ratio:.0%} of the "
            f"{w.thread_ceiling} ceiling — thread-pool exhaustion risk under load",
            ["jvm", "threads"],
        )
    return None
