"""Render recommendations for Slack, a PR comment, or the terminal.

Leads with the number a manager cares about (annualized savings), then splits
findings into cost wins and reliability risks — because a right-sizing report
that hides the "this will OOM" items is worse than no report.
"""
from __future__ import annotations

from collections import defaultdict

from .models import Category, Recommendation
from .recommender import total_monthly_savings


def summarize(recs: list[Recommendation]) -> dict:
    by_dim: dict[str, float] = defaultdict(float)
    for r in recs:
        if r.category is Category.COST:
            by_dim[r.dimension] += r.monthly_savings
    monthly = round(total_monthly_savings(recs), 2)
    return {
        "findings": len(recs),
        "cost_findings": sum(1 for r in recs if r.category is Category.COST),
        "reliability_findings": sum(1 for r in recs if r.category is Category.RELIABILITY),
        "monthly_savings": monthly,
        "annual_savings": round(monthly * 12, 2),
        "savings_by_dimension": {k: round(v, 2) for k, v in sorted(by_dim.items(), key=lambda x: -x[1])},
    }


def render_text(recs: list[Recommendation]) -> str:
    s = summarize(recs)
    cost = [r for r in recs if r.category is Category.COST]
    rel = [r for r in recs if r.category is Category.RELIABILITY]
    out = [
        f"GKE right-sizing: {s['findings']} findings — "
        f"${s['monthly_savings']:,.0f}/mo (${s['annual_savings']:,.0f}/yr) reclaimable, "
        f"{s['reliability_findings']} reliability risk(s)",
        "=" * 78,
        "COST — reclaim over-provisioned requests",
        "-" * 78,
    ]
    for r in cost:
        out.append(f"[{r.severity.value.upper():6}] {r.workload_id:28} ${r.monthly_savings:>7,.0f}/mo  {r.detail}")
    out += ["", "RELIABILITY — fix before (or instead of) cutting", "-" * 78]
    for r in rel:
        out.append(f"[{r.severity.value.upper():6}] {r.workload_id:28} {r.dimension:12} {r.detail}")
    return "\n".join(out)


def render_markdown(recs: list[Recommendation]) -> str:
    s = summarize(recs)
    lines = [
        "# ⚙️ GKE right-sizing report",
        "",
        f"**{s['findings']} findings** — **${s['monthly_savings']:,.0f}/mo "
        f"(${s['annual_savings']:,.0f}/yr)** reclaimable across {s['cost_findings']} workloads, "
        f"plus **{s['reliability_findings']} reliability risk(s)** to fix first.",
        "",
        "## 💸 Cost — reclaim over-provisioned requests",
        "| Severity | Workload | Change | Est. monthly savings |",
        "| --- | --- | --- | ---: |",
    ]
    for r in (x for x in recs if x.category is Category.COST):
        lines.append(f"| {r.severity.value.upper()} | `{r.workload_id}` | {r.detail} | ${r.monthly_savings:,.0f} |")
    lines += ["", "## 🛡️ Reliability — fix before cutting", "| Severity | Workload | Dimension | Issue |", "| --- | --- | --- | --- |"]
    for r in (x for x in recs if x.category is Category.RELIABILITY):
        lines.append(f"| {r.severity.value.upper()} | `{r.workload_id}` | {r.dimension} | {r.detail} |")
    lines += ["", "<details><summary>Rationale for every finding</summary>", ""]
    for r in recs:
        lines.append(f"- **{r.workload_id}** ({r.dimension}) — {r.rationale}.")
    lines += ["", "</details>"]
    return "\n".join(lines)
