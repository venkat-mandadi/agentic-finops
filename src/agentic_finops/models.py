"""Core data models for the GKE workload right-sizing engine.

The engine operates on **workloads** (a Deployment/StatefulSet container),
not billing line items. For each one it pulls a utilization signal from
Prometheus and decides whether the CPU/memory requests and limits are right —
without starving the app at startup or OOM-killing it in production.

All CPU is in millicores (m), all memory in MiB. Utilization fields are
*observed* values from Prometheus over the analysis window.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Runtime(str, Enum):
    JVM = "jvm"
    OTHER = "other"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Category(str, Enum):
    COST = "cost"              # reclaim over-provisioned requests
    RELIABILITY = "reliability"  # fix under-provisioning / throttling / OOM


@dataclass(frozen=True)
class Workload:
    """A single workload container plus its observed utilization.

    Steady-state metrics (``cpu_p95_m``, ``mem_peak_mi`` …) are computed with
    the **startup window excluded**, because JVM apps spike hard while the JIT
    warms and classes load. Startup peaks are captured separately so we never
    recommend a size that would throttle or OOM the app during boot.
    """

    namespace: str
    workload: str
    kind: str                      # Deployment | StatefulSet
    cluster: str
    project: str
    replicas: int
    runtime: Runtime

    # current spec
    cpu_request_m: int
    cpu_limit_m: int               # 0 == unset
    mem_request_mi: int
    mem_limit_mi: int              # 0 == unset

    # observed, steady-state (startup excluded)
    cpu_avg_m: float
    cpu_p95_m: float
    mem_avg_mi: float
    mem_peak_mi: float             # working-set peak — memory must be sized to this

    # startup window (JVM warm-up)
    startup_cpu_peak_m: float = 0.0
    startup_mem_peak_mi: float = 0.0
    startup_secs: float = 0.0

    # JVM internals (0 for non-JVM)
    heap_max_mi: int = 0           # -Xmx
    heap_used_peak_mi: float = 0.0
    nonheap_used_mi: float = 0.0
    threads_peak: int = 0
    thread_ceiling: int = 0        # pool / ulimit ceiling if known

    # health signals
    cpu_throttle_pct: float = 0.0  # fraction of CFS periods throttled (0..1)
    oom_killed: int = 0
    restarts: int = 0

    # Goldilocks / VPA recommendation (target requests)
    vpa_cpu_target_m: int = 0
    vpa_mem_target_mi: int = 0

    @property
    def id(self) -> str:
        return f"{self.namespace}/{self.workload}"


@dataclass(frozen=True)
class NodeCost:
    """Blended node cost used to translate reclaimed *requests* into money.

    On GKE you pay for the nodes your requests reserve, so right-sizing
    requests improves bin-packing and removes nodes. Defaults are
    representative on-demand e2 figures; override per cluster.
    """
    cpu_core_month: float = 16.0   # $ / vCPU-month
    mem_gib_month: float = 2.1     # $ / GiB-month


@dataclass(frozen=True)
class Recommendation:
    workload_id: str
    project: str
    dimension: str                 # cpu_request | mem_request | cpu_limit | mem_limit | jvm | threads
    action: str                    # downsize | raise | set | remove | tune
    detail: str                    # e.g. "cpu request 1000m -> 350m"
    category: Category
    severity: Severity
    monthly_savings: float         # >0 only for cost actions; 0 for reliability
    rationale: str
    tags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "workload": self.workload_id,
            "project": self.project,
            "dimension": self.dimension,
            "action": self.action,
            "detail": self.detail,
            "category": self.category.value,
            "severity": self.severity.value,
            "monthly_savings": round(self.monthly_savings, 2),
            "annual_savings": round(self.monthly_savings * 12, 2),
            "rationale": self.rationale,
            "tags": self.tags,
        }
