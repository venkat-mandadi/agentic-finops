"""Recommender-level tests: ranking, savings math, report shape."""
from pathlib import Path

import pytest

from agentic_finops import metrics, recommender, report
from agentic_finops.models import Category

SAMPLE = Path(__file__).parent.parent / "examples" / "sample_workloads.csv"


@pytest.fixture
def recs():
    return recommender.analyze(metrics.load_from_csv(SAMPLE))


def test_cost_recommendations_come_first_and_sorted(recs):
    cost = [r for r in recs if r.category is Category.COST]
    savings = [r.monthly_savings for r in cost]
    assert savings == sorted(savings, reverse=True)
    # the biggest cost item should outrank every reliability item in the list
    first_reliability = next(i for i, r in enumerate(recs) if r.category is Category.RELIABILITY)
    assert all(r.category is Category.COST for r in recs[:first_reliability])


def test_total_savings_only_counts_cost(recs):
    total = recommender.total_monthly_savings(recs)
    assert total == pytest.approx(
        sum(r.monthly_savings for r in recs if r.category is Category.COST)
    )
    assert total > 0


def test_savings_scale_with_replicas(recs):
    # batch-processor reserves 2000m over 10 replicas -> should be a large win
    batch = next(r for r in recs if r.workload_id.endswith("batch-processor")
                 and r.dimension == "cpu_request")
    assert batch.monthly_savings > 200      # HIGH severity territory
    assert batch.severity.value == "high"


def test_summary_math(recs):
    s = report.summarize(recs)
    assert s["findings"] == len(recs)
    assert s["annual_savings"] == pytest.approx(s["monthly_savings"] * 12)
    assert s["cost_findings"] + s["reliability_findings"] == s["findings"]


def test_markdown_report_has_both_sections(recs):
    md = report.render_markdown(recs)
    assert "Cost" in md and "Reliability" in md
    assert "reclaimable" in md


def test_reliability_findings_have_zero_savings(recs):
    for r in recs:
        if r.category is Category.RELIABILITY:
            assert r.monthly_savings == 0.0
