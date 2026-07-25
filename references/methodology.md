# Methodology — detection rules, thresholds, and savings math

Load this only when you need to explain *why* the engine made a call, tune its
behavior, or wire it to real data. A normal scan doesn't need any of it.

## Contents
- [The signal](#the-signal)
- [Thresholds](#thresholds)
- [Cost rules](#cost-rules)
- [Reliability rules](#reliability-rules)
- [Savings model](#savings-model)
- [Wiring real Prometheus data](#wiring-real-prometheus-data)

## The signal

One row per workload container, over a rolling window (default 1 day). Steady-
state metrics **exclude the startup window** — JVM warm-up (JIT, class loading)
spikes CPU and memory and would otherwise poison every recommendation. Startup
peaks are captured *separately* so they can act as a floor. The full schema is
`examples/sample_workloads.csv`; the model is `src/agentic_finops/models.py`.

## Thresholds

All in `src/agentic_finops/policy.py` — one `Policy` object so every finding can
name the knob it tripped. Defaults are deliberately conservative (a bad downsize
causes an outage; a missed one costs a few dollars).

| Knob | Default | Meaning |
| --- | --- | --- |
| `cpu_headroom` | 1.30 | CPU request target = p95 × this (or VPA target, whichever is higher) |
| `mem_headroom` | 1.15 | memory target = max(peak, startup peak, VPA) × this |
| `jvm_overhead_mi` | 256 | buffer above `-Xmx` + non-heap (metaspace, thread stacks, direct, code cache) |
| `over_request_ratio` | 1.5 | only downsize when request > 1.5× need |
| `cpu_throttle_flag` | 0.10 | >10% of CFS periods throttled = throttled |
| `mem_peak_limit_ratio` | 0.90 | peak > 90% of limit = OOM risk |
| `thread_ceiling_ratio` | 0.85 | threads peak > 85% of ceiling = pressure |
| `min_cpu_reclaim_m` / `min_mem_reclaim_mi` | 100m / 128Mi | ignore trivial changes |

## Cost rules

Reclaim over-provisioned **requests** (what reserves node capacity).

- **CPU request** → `max(p95 × cpu_headroom, VPA target)`, rounded to 10m. Only
  fires if the reclaim clears `min_cpu_reclaim_m` and the request exceeds the
  target by `over_request_ratio`.
- **Memory request** → `max(working-set peak, startup peak, VPA) × mem_headroom`,
  rounded to 16Mi, then floored by the JVM rule below.

## Reliability rules

These carry **zero savings** — they exist so right-sizing doesn't cause the
outage it was meant to prevent. They're surfaced before cost.

- **Under-provisioned CPU/memory** — usage at/over the request → *raise* it.
- **CPU throttling** — `cpu_throttle_pct > cpu_throttle_flag` with a CPU limit
  set → raise or remove the limit.
- **Startup CPU** — `startup_cpu_peak > cpu_limit` → the app is throttled during
  warm-up; readiness probes flake. Raise the limit.
- **OOM risk** — observed OOM-kills, or `mem_peak > mem_limit × mem_peak_limit_ratio`
  → raise the memory limit.
- **JVM heap vs. limit** — `-Xmx + non-heap + jvm_overhead_mi > mem_limit` → the
  container OOMs under load. Lower `-Xmx` (or use `-XX:MaxRAMPercentage`) or
  raise the limit.
- **Thread pressure** — `threads_peak > thread_ceiling × thread_ceiling_ratio`
  → thread-pool exhaustion risk.

## Savings model

GKE bills for the nodes your **requests** reserve, so savings come from reclaimed
requests improving bin-packing:

```
monthly_savings = (reclaimed_vCPU  × cpu_core_month
                 + reclaimed_GiB   × mem_gib_month) × replicas
```

`NodeCost` defaults (`cpu_core_month = $16`, `mem_gib_month = $2.1`) are
representative on-demand e2 figures — override per cluster. Only reductions
count as savings; reliability *raises* are reported at $0 (they're
risk-avoidance, not spend).

## Wiring real Prometheus data

Swap `metrics.load_from_csv` for `load_from_prometheus`. The real query shapes
are in `metrics.PROMQL`:

- **steady-state CPU p95** — `quantile_over_time(0.95, rate(container_cpu_usage_seconds_total[5m])[1d:5m])`, guarded by `time() - container_start_time_seconds > 300` to drop the startup window
- **memory peak** — `max_over_time(container_memory_working_set_bytes[1d])`
- **throttling** — `rate(container_cpu_cfs_throttled_periods_total[1d]) / rate(container_cpu_cfs_periods_total[1d])`
- **JVM heap / threads** — `jvm_memory_used_bytes{area="heap"}`, `jvm_threads_live_threads`
- **restarts** — `increase(kube_pod_container_status_restarts_total[1d])`

Join each result with the live pod spec (requests/limits) and the workload's
Goldilocks/VPA object, map into the `Workload` schema, and the rest of the
pipeline is unchanged.
