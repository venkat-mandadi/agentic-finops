"""Detection-rule tests against the sample workload set."""
from pathlib import Path

import pytest

from agentic_finops import metrics, recommender
from agentic_finops.models import Category

SAMPLE = Path(__file__).parent.parent / "examples" / "sample_workloads.csv"


@pytest.fixture
def recs():
    return recommender.analyze(metrics.load_from_csv(SAMPLE))


def _for(recs, workload):
    return [r for r in recs if r.workload_id.endswith(workload)]


def test_sample_loads():
    w = metrics.load_from_csv(SAMPLE)
    assert len(w) == 8


def test_healthy_workload_gets_no_recommendations(recs):
    # a well-sized app must not be flagged at all
    assert _for(recs, "healthy-api") == []


def test_cpu_over_request_is_downsized(recs):
    r = [x for x in _for(recs, "payments-api") if x.dimension == "cpu_request"]
    assert r and r[0].action == "downsize" and r[0].category is Category.COST
    assert r[0].monthly_savings > 0


def test_memory_never_recommended_below_jvm_floor(recs):
    # payments-api: -Xmx 1024 + non-heap 300 + overhead 256 = 1580 floor
    r = [x for x in _for(recs, "payments-api") if x.dimension == "mem_request"]
    assert r
    target = int(r[0].detail.split("-> ")[1].split("Mi")[0])
    assert target >= 1580


def test_cpu_throttling_is_flagged(recs):
    r = [x for x in _for(recs, "catalog-worker") if "throttl" in x.rationale.lower()]
    assert r and r[0].category is Category.RELIABILITY


def test_oom_and_heap_mismatch_flagged(recs):
    dims = {x.dimension for x in _for(recs, "checkout-svc")}
    assert "mem_limit" in dims   # OOM risk
    assert "jvm" in dims         # -Xmx exceeds container limit


def test_startup_spike_protects_cpu_limit(recs):
    # legacy-monolith: request can drop, but the LIMIT must clear the 2600m startup peak
    items = _for(recs, "legacy-monolith")
    assert any(x.dimension == "cpu_request" and x.action == "downsize" for x in items)
    assert any(x.dimension == "cpu_limit" and "startup" in x.rationale.lower() for x in items)


def test_under_provisioned_cpu_is_raised(recs):
    r = [x for x in _for(recs, "reporting-svc") if x.dimension == "cpu_request"]
    assert r and r[0].action == "raise" and r[0].category is Category.RELIABILITY


def test_thread_pressure_flagged(recs):
    r = [x for x in _for(recs, "notifications") if x.dimension == "threads"]
    assert r and r[0].category is Category.RELIABILITY
