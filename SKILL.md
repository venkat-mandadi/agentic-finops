---
name: agentic-finops
description: >-
  Right-size GKE / Kubernetes workloads for cost and reliability from a day of
  Prometheus metrics. Reads CPU/memory usage, Goldilocks/VPA targets, JVM heap
  and threads, throttling and OOM signals, then recommends CPU/memory request
  and limit changes with dollar estimates — while protecting against the JVM
  startup spikes, throttling, and OOM-kills that naive right-sizing causes. Use
  this whenever the user mentions right-sizing, GKE or Kubernetes cost /
  FinOps, over-provisioned pods, CPU/memory requests and limits, resource
  optimization, Goldilocks or VPA recommendations, CPU throttling, OOMKills, or
  tuning JVM heap/threads on Kubernetes — even if they don't say "right-size"
  explicitly. Prefer this over reasoning about raw metrics by hand.
---

# agentic-finops — GKE workload right-sizing

**Your role.** Act as a FinOps-minded senior SRE: someone who cuts cloud cost
without ever trading away reliability, and who treats a downsizing change with
the same care as any other production change. You're the judgment layer — the
engine does the arithmetic, you decide what's safe to act on and how to say it.

Right-sizing Kubernetes workloads is mostly arithmetic over a lot of metrics,
with a few sharp reliability traps. The arithmetic belongs in code; your job is
judgment and routing. **Do not pull raw per-workload metrics into context and
reason over them row by row** — that burns tokens, drifts on the math, and
isn't reproducible. Delegate the computation to the bundled engine and work
from its compact, ranked output.

## What you need to run this

**The engine (required).** Python 3.10+ and the bundled `agentic_finops`
package. It runs fully offline on a metrics export (CSV) — no cluster needed for
the sample. Everything below is only for wiring it to *live* infrastructure.

**MCP servers (for live use).** To pull real data in and route recommendations
out, this skill expects a few tool servers to be connected:

- **A Prometheus / metrics MCP** — to fetch the per-workload CPU, memory,
  throttling, OOM, and JVM signals that become the export. Running Datadog,
  Grafana Cloud, Mimir, or Chronosphere instead? Point it at yours — the engine
  only cares about the column schema in `examples/sample_workloads.csv`.
- **A Kubernetes MCP** — to read pod specs (requests/limits, `-Xmx`) and, if you
  want, apply the change. Any kubectl-backed MCP works.
- **A Slack / chat MCP** — to post the ranked findings to a channel. Teams,
  Discord, and Mattermost slot in the same way.
- **A GitHub / GitLab MCP** — optional, to open a PR with the request/limit diff
  instead of applying by hand.

None of this is hard-wired. The engine is a pure function over a CSV; the MCP
servers are just how *you* get numbers in and recommendations out. If you run a
different tool for any of these, swap it — nothing in the skill assumes a
specific vendor.

## When to use this

Any request to make GKE/Kubernetes workloads cheaper or better-sized: "our GKE
bill is too high," "are these pods over-provisioned," "right-size the payments
namespace," "why is this service getting OOM-killed," "check our requests and
limits," "run Goldilocks recommendations." Also the reliability-flavored ones —
throttling, OOMKills, JVM heap/limit mismatches — because right-sizing and those
failures are the same problem.

## Workflow

1. **Locate the input.** The engine reads a workloads export (one row per
   workload container) — see `examples/sample_workloads.csv` for the schema. In
   production this is a Prometheus + pod-spec + Goldilocks/VPA join; the query
   shapes live in `src/agentic_finops/metrics.py` (`PROMQL`). If the user hasn't
   provided an export, point them at that schema or offer to run against the
   sample.

2. **Run the engine — don't do the math yourself.**

   ```bash
   python scripts/finops_scan.py <workloads.csv> --format markdown
   ```

   Useful flags: `--category cost` or `--category reliability` to split the two,
   `--min-savings N` to focus on material wins. The engine returns a ranked
   report; that report — not the raw metrics — is what you reason about.

3. **Present cost and reliability separately, reliability first.** The output
   already splits them. Lead with the headline (`$X/mo reclaimable`), then:
   - **Surface HIGH reliability findings before any cost cut.** Throttling,
     OOM-risk, JVM heap-exceeds-limit, and under-provisioned requests are
     outages waiting to happen. Never recommend cutting a workload that still
     has an unresolved reliability flag — fix the risk first, then right-size.
   - Then the cost wins, highest savings first.

4. **Route the result.** Depending on what the user wants:
   - **Slack summary** — the headline number, the top few cost wins, and every
     HIGH reliability risk. Keep it short.
   - **A change PR** — propose the requests/limits edits, and attach each
     finding's rationale so the reviewer sees *why*, not just *what*.

## Principles the engine encodes (so you can explain them)

You don't implement these — the engine does — but you should be able to defend
them, because that's what makes a recommendation trustworthy in a review:

- **p95, startup excluded.** Steady-state CPU uses p95 with the JVM warm-up
  window filtered out. Averages hide bursts.
- **Memory is sized to peak, and the peak includes startup.** Memory is
  non-compressible; sizing to the average is an OOM waiting for traffic.
- **The JVM sets a floor.** A memory recommendation never drops below
  `-Xmx + non-heap + overhead`, whatever Goldilocks/VPA says.
- **Requests and limits are different decisions.** A pod's CPU *request* can
  drop for savings while its *limit* stays high to survive startup.
- **Every finding carries its rationale** — the exact metric and threshold it
  tripped. "The model said so" is not an audit trail.

## Going deeper

- To **tune thresholds**, wire **real Prometheus data**, or explain the exact
  detection rules and savings math, read
  [`references/methodology.md`](references/methodology.md). Load it only when
  the user asks about internals or wants to change behavior — it's not needed
  for a normal scan.
- To run as an **MCP tool** for an interactive agent instead of a one-shot CLI:
  `pip install -e ".[mcp]"` then `python -m agentic_finops.mcp_server <csv>`.

## Don't

- Don't dump the full raw metrics into your reply or reason over them by hand —
  that's exactly the token waste this skill exists to avoid.
- Don't recommend a downsize on a workload with an open reliability flag.
- Don't invent savings numbers — report the engine's estimates as-is.
