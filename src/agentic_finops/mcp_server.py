"""MCP server exposing the right-sizing engine as agent tools.

Lets a Claude agent scan a cluster's workloads, pull ranked recommendations,
and render a report for Slack or a PR — while the risky decision logic stays
deterministic and testable underneath.

    python -m agentic_finops.mcp_server /path/to/workloads.csv

The ``mcp`` package is optional (pip install "agentic-finops[mcp]") so the
core engine and its tests stay dependency-free.
"""
from __future__ import annotations

import sys

from . import metrics, recommender, report

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None


def build_server(workloads_csv: str) -> FastMCP:
    if FastMCP is None:  # pragma: no cover
        raise SystemExit('The "mcp" package is required. Install: pip install "agentic-finops[mcp]"')

    mcp = FastMCP("agentic-finops")

    def _load():
        return metrics.load_from_csv(workloads_csv)

    @mcp.tool()
    def scan_workloads() -> dict:
        """Right-size every workload and return a savings + risk summary."""
        return report.summarize(recommender.analyze(_load()))

    @mcp.tool()
    def get_recommendations(category: str = "", min_monthly_savings: float = 0.0) -> list[dict]:
        """Ranked recommendations. category = 'cost' | 'reliability' | '' (all)."""
        recs = recommender.analyze(_load())
        return [
            r.as_dict() for r in recs
            if (not category or r.category.value == category)
            and r.monthly_savings >= min_monthly_savings
        ]

    @mcp.tool()
    def rightsizing_report(fmt: str = "markdown") -> str:
        """Full report. fmt = 'markdown' | 'text'."""
        recs = recommender.analyze(_load())
        return report.render_markdown(recs) if fmt == "markdown" else report.render_text(recs)

    return mcp


def main() -> None:  # pragma: no cover
    if len(sys.argv) < 2:
        print("usage: python -m agentic_finops.mcp_server <workloads.csv>", file=sys.stderr)
        raise SystemExit(2)
    build_server(sys.argv[1]).run()


if __name__ == "__main__":  # pragma: no cover
    main()
