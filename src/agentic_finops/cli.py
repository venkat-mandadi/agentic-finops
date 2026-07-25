"""Command-line entry point:

    finops-scan <workloads.csv> [--format text|markdown] [--category cost|reliability]

A thin wrapper over the engine so you can run a scan without an MCP client.
"""
from __future__ import annotations

import argparse

from . import metrics, recommender, report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="finops-scan", description="Right-size GKE workloads from a Prometheus export.")
    p.add_argument("workloads_csv", help="Path to a workloads CSV export (see examples/).")
    p.add_argument("--format", choices=["text", "markdown"], default="text")
    p.add_argument("--category", choices=["cost", "reliability"], default=None)
    p.add_argument("--min-savings", type=float, default=0.0)
    args = p.parse_args(argv)

    recs = recommender.analyze(metrics.load_from_csv(args.workloads_csv))
    if args.category:
        recs = [r for r in recs if r.category.value == args.category]
    recs = [r for r in recs if r.monthly_savings >= args.min_savings]

    print(report.render_markdown(recs) if args.format == "markdown" else report.render_text(recs))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
