"""Tunable policy for right-sizing decisions.

Everything that could be argued about in a review lives here, in one place,
so a recommendation can always point at the exact knob it tripped. Defaults
are deliberately conservative — the cost of a bad downsize (an outage) dwarfs
the cost of leaving a little slack on the table.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Policy:
    # CPU request target = max(p95 * headroom, VPA target)
    cpu_headroom: float = 1.30
    # Memory request/limit target = max(peak, startup_peak, jvm_floor) * headroom
    mem_headroom: float = 1.15
    # JVM: container memory must clear heap + non-heap + this overhead (metaspace,
    # thread stacks, direct buffers, code cache) or it OOMs under load.
    jvm_overhead_mi: int = 256

    # act only when the win is real
    min_cpu_reclaim_m: int = 100        # ignore sub-0.1 core changes
    min_mem_reclaim_mi: int = 128
    over_request_ratio: float = 1.5     # request > 1.5x need = worth downsizing

    # reliability triggers
    cpu_throttle_flag: float = 0.10     # >10% CFS periods throttled = throttled
    mem_peak_limit_ratio: float = 0.90  # peak > 90% of limit = OOM risk
    thread_ceiling_ratio: float = 0.85  # threads_peak > 85% of ceiling = pressure

    def cpu_target_m(self, cpu_p95_m: float, vpa_cpu_target_m: int) -> int:
        want = cpu_p95_m * self.cpu_headroom
        if vpa_cpu_target_m:
            want = max(want, vpa_cpu_target_m)
        return int(round(want / 10.0) * 10)   # round to 10m

    def mem_target_mi(self, w) -> int:
        """Memory floor is the interesting bit: it must cover the working-set
        peak, the *startup* peak, and — for the JVM — the heap ceiling."""
        drivers = [w.mem_peak_mi, w.startup_mem_peak_mi]
        if w.vpa_mem_target_mi:
            drivers.append(w.vpa_mem_target_mi)
        want = max(drivers) * self.mem_headroom
        if w.runtime.value == "jvm" and w.heap_max_mi:
            jvm_floor = w.heap_max_mi + w.nonheap_used_mi + self.jvm_overhead_mi
            want = max(want, jvm_floor)
        return int(round(want / 16.0) * 16)   # round to 16Mi
