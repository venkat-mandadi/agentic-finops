"""agentic-finops — an MCP-driven GKE workload right-sizing agent.

Pulls a utilization signal from Prometheus, right-sizes CPU/memory requests
and limits, and guards the JVM failure modes (startup spikes, heap vs. limit,
throttling, OOM) so cost cuts never turn into incidents.

Public API:
    from agentic_finops import metrics, rules, recommender, report
"""
from . import metrics, recommender, report, rules
from .models import Category, NodeCost, Recommendation, Runtime, Severity, Workload
from .policy import Policy

__version__ = "0.2.0"

__all__ = [
    "Category",
    "NodeCost",
    "Policy",
    "Recommendation",
    "Runtime",
    "Severity",
    "Workload",
    "metrics",
    "recommender",
    "report",
    "rules",
]
