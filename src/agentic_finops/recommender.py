"""Run every rule over every workload and assemble a ranked result set."""
from __future__ import annotations

from . import rules
from .models import Category, NodeCost, Recommendation, Workload
from .policy import Policy


def analyze(
    workloads: list[Workload],
    policy: Policy | None = None,
    cost: NodeCost | None = None,
) -> list[Recommendation]:
    p = policy or Policy()
    c = cost or NodeCost()
    out: list[Recommendation] = []

    for w in workloads:
        for rec in (
            rules.rightsize_cpu(w, p, c),
            rules.rightsize_memory(w, p, c),
            rules.check_cpu_throttling(w, p),
            rules.check_startup_cpu_limit(w),
            rules.check_oom(w, p),
            rules.check_jvm_heap(w, p),
            rules.check_threads(w, p),
        ):
            if rec is not None:
                out.append(rec)

    # cost wins first (by savings), then reliability risks (by severity)
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda r: (
        r.category is not Category.COST,
        -r.monthly_savings,
        sev_rank[r.severity.value],
    ))
    return out


def total_monthly_savings(recs: list[Recommendation]) -> float:
    return sum(r.monthly_savings for r in recs if r.category is Category.COST)
