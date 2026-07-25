"""Load workloads + their utilization signal.

In production this queries **Prometheus** (GKE / Google Managed Prometheus)
over a rolling window and joins the result with the live pod spec and, where
present, the workload's Goldilocks/VPA recommendation. The PromQL below is the
real shape of those queries; the startup window is excluded from steady-state
metrics because JVM warm-up would otherwise inflate every number.

This open version ships an equivalent **CSV loader** so the whole pipeline runs
offline against the sample data in ``examples/``. Swap ``load_from_csv`` for
``load_from_prometheus`` and nothing downstream changes.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .models import Runtime, Workload

# Reference PromQL (documented, not executed here) --------------------------
PROMQL = {
    # steady-state CPU, startup excluded via the (time() - start > 300s) guard
    "cpu_p95": (
        'quantile_over_time(0.95, '
        'rate(container_cpu_usage_seconds_total{container!="POD"}[5m])[1d:5m]) '
        '* 1000 and on() (time() - container_start_time_seconds > 300)'
    ),
    "mem_peak": 'max_over_time(container_memory_working_set_bytes[1d]) / 1024 / 1024',
    "startup_cpu_peak": (
        'max_over_time(rate(container_cpu_usage_seconds_total[1m])[5m:] '
        '@ container_start_time_seconds) * 1000'
    ),
    "cpu_throttle": (
        'rate(container_cpu_cfs_throttled_periods_total[1d]) '
        '/ rate(container_cpu_cfs_periods_total[1d])'
    ),
    "jvm_heap_used": 'max_over_time(jvm_memory_used_bytes{area="heap"}[1d]) / 1024 / 1024',
    "jvm_threads": 'max_over_time(jvm_threads_live_threads[1d])',
    "restarts": 'increase(kube_pod_container_status_restarts_total[1d])',
}


def _f(row: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, "") or default)
    except ValueError:
        return default


def _i(row: dict, key: str, default: int = 0) -> int:
    return int(_f(row, key, default))


def load_from_csv(path: str | Path) -> list[Workload]:
    """Read workloads from a CSV export matching the Prometheus/spec join."""
    out: list[Workload] = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            out.append(Workload(
                namespace=row["namespace"],
                workload=row["workload"],
                kind=row.get("kind", "Deployment"),
                cluster=row.get("cluster", ""),
                project=row["project"],
                replicas=_i(row, "replicas", 1),
                runtime=Runtime(row.get("runtime", "other").strip().lower()),
                cpu_request_m=_i(row, "cpu_request_m"),
                cpu_limit_m=_i(row, "cpu_limit_m"),
                mem_request_mi=_i(row, "mem_request_mi"),
                mem_limit_mi=_i(row, "mem_limit_mi"),
                cpu_avg_m=_f(row, "cpu_avg_m"),
                cpu_p95_m=_f(row, "cpu_p95_m"),
                mem_avg_mi=_f(row, "mem_avg_mi"),
                mem_peak_mi=_f(row, "mem_peak_mi"),
                startup_cpu_peak_m=_f(row, "startup_cpu_peak_m"),
                startup_mem_peak_mi=_f(row, "startup_mem_peak_mi"),
                startup_secs=_f(row, "startup_secs"),
                heap_max_mi=_i(row, "heap_max_mi"),
                heap_used_peak_mi=_f(row, "heap_used_peak_mi"),
                nonheap_used_mi=_f(row, "nonheap_used_mi"),
                threads_peak=_i(row, "threads_peak"),
                thread_ceiling=_i(row, "thread_ceiling"),
                cpu_throttle_pct=_f(row, "cpu_throttle_pct"),
                oom_killed=_i(row, "oom_killed"),
                restarts=_i(row, "restarts"),
                vpa_cpu_target_m=_i(row, "vpa_cpu_target_m"),
                vpa_mem_target_mi=_i(row, "vpa_mem_target_mi"),
            ))
    return out


def load_from_prometheus(prom_url: str, window: str = "1d"):  # pragma: no cover
    """Production loader (stub).

    Run the queries in ``PROMQL`` against ``prom_url`` for each workload, join
    with the pod spec (requests/limits) and the Goldilocks/VPA object, and map
    into ``Workload``. Left as a stub because it needs a live Prometheus and
    cluster access to be meaningful.
    """
    raise NotImplementedError(
        "Point this at your Prometheus and join with pod spec + VPA. "
        "See PROMQL for the query shapes and load_from_csv for the target schema."
    )
