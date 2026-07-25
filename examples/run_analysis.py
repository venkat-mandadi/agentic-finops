"""Runnable demo — no cluster or Prometheus required.

    python examples/run_analysis.py

Loads the sample workload export, runs the full right-sizing pipeline, and
prints the report.
"""
from pathlib import Path

from agentic_finops import metrics, recommender, report

HERE = Path(__file__).parent


def main() -> None:
    workloads = metrics.load_from_csv(HERE / "sample_workloads.csv")
    recs = recommender.analyze(workloads)

    print(report.render_text(recs))
    print()

    s = report.summarize(recs)
    print("Savings by dimension:")
    for dim, amount in s["savings_by_dimension"].items():
        print(f"  {dim:14} ${amount:,.0f}/mo")


if __name__ == "__main__":
    main()
