---
name: stream-aggregation-helper
description: >
  Design VictoriaMetrics stream aggregation rules to reduce cardinality, sample frequency, or query
  load. Use whenever the user wants to apply, plan, or troubleshoot stream aggregation (`-streamAggr.config`,
  `-remoteWrite.streamAggr.config`), asks how to aggregate a high-cardinality metric, mentions
  downsampling at vmagent, replacing recording rules with stream aggregation, picking the right
  aggregation output (`total`, `rate_sum`, `sum_samples`, `quantiles`, `histogram_bucket`, etc.),
  choosing an aggregation interval, deciding where to place vmagent in the delivery pipeline, or
  whether to scale vmagent for aggregation. Also triggers on "aggregate histograms", "drop labels
  via vmagent", "reduce ingested samples", "pre-aggregate at vmagent", "stream aggregation accuracy",
  and "stream aggregation duplicates in cluster".
allowed-tools: Bash(curl:*), Bash(jq:*)
---

# Stream Aggregation Helper

Design, deploy, and verify [stream aggregation](https://docs.victoriametrics.com/victoriametrics/stream-aggregation/) rules
for VictoriaMetrics. Stream aggregation reduces cardinality, sample frequency, or query cost by aggregating samples
**by time and by labels** at `vmagent` (or single-node vmsingle) **before** they reach storage.

The skill walks through five phases:

1. **Gate** — is stream aggregation the right tool for this problem?
2. **Intake** — current cardinality, collection topology, what consumers need.
3. **Decide** — where in the pipeline, interval, output function, `by`/`without`, scaling.
4. **Config** — produce a ready-to-apply YAML plus a phased rollout plan.
5. **Verify** — queries and `vm_streamaggr_*` metrics that confirm the rule is doing what was intended.

## Environment

Uses the same env vars as the `victoriametrics-query` skill. The skill works **without** these (interview-only
mode) but is much more accurate when it can query the user's VictoriaMetrics directly.

```bash
# $VM_METRICS_URL - base URL (optional)
#   cluster: export VM_METRICS_URL="https://vmselect.example.com/select/0/prometheus"
#   single:  export VM_METRICS_URL="http://localhost:8428"
# $VM_AUTH_HEADER - full HTTP header line (empty if no auth)
#   Prod:  export VM_AUTH_HEADER="Authorization: Bearer <token>"
#   Local: export VM_AUTH_HEADER=""
```

---

## Phase 1: Is stream aggregation the right tool?

Stream aggregation is the right answer when **all** of these hold:

- For every output series that the rule will produce, **all** input samples that contribute to it
  land on a single aggregator process. This holds in three common topologies:
  1. A single `vmagent` (or vmsingle) sees every sample for the matched series.
  2. Multiple vmagents shard traffic by some label (e.g., `instance`, `kubernetes_namespace`,
     `__name__`) and the aggregation **preserves that shard key** — see the shard-key invariant in
     Phase 3a (case F). Tiered topologies like *tier-1 vmagents shard by `instance` → tier-2
     vmagents aggregate within `instance`* are explicitly supported.
  3. HA replicas all see every sample **and** the aggregation output is dedup-safe (gauge-style:
     `min`, `max`, `avg`, `rate_*`, `increase*`, `last`, `quantiles`, etc.). Counter-style outputs
     (`total`, `total_prometheus`, `histogram_bucket`) cannot be HA-aggregated because each replica
     maintains independent monotonic state. See the High Availability section.
- The user is willing to lose per-source resolution (per-pod, per-instance) for the matched metric,
  OR only wants to drop a high-cardinality label they don't actually consume.
- Consumers (dashboards, alerts, recording rules) either don't need the dropped dimensions, or can
  be migrated to the aggregated metric name.
- State loss on `vmagent` restart is acceptable. Aggregation state is in-memory; on restart the
  first one or two intervals are discarded by default.

**Shard-key invariant**: an output series is correct only if every input sample for it goes to the
same aggregator. Translated to rules: the labels used to shard the stream must appear in `by:` (or
must not appear in `without:`) of every aggregation rule downstream of the shard. Drop them and you
get partial aggregates per shard — silently wrong.

If any of these fail, redirect the user:

| Situation | Better tool |
|-----------|-------------|
| Need to drop entire unused metrics | `metric_relabel_configs` with `action: drop` — see `victoriametrics-unused-metrics-analysis` |
| Need to drop labels without time-bucketing | `metric_relabel_configs` with `action: labeldrop`, or `-streamAggr.dropInputLabels` |
| Need historical downsampling on existing data | vmstorage downsampling (`-downsampling.period`) |
| Want a derived metric for queries, not ingestion | Recording rules in vmalert |
| Single-node setup but stream-aggregating before storage | `-streamAggr.config` on vmsingle is fine — same engine; just say so |
| Behind a load balancer that splits the stream (round-robin) | Shard traffic deterministically by labels (`-remoteWrite.shardByURL.labels`), then aggregate while preserving the shard key. Round-robin LBs split a single output series across replicas → incomplete results. See [Common Mistakes › Behind load balancer](https://docs.victoriametrics.com/victoriametrics/stream-aggregation/#put-aggregator-behind-load-balancer) |
| Tiered vmagents (tier-1 shards, tier-2 aggregates) | Supported and common at scale. Aggregation rules on tier-2 must **keep the shard key** in `by:` (or omit it from `without:`). See case F below. |

If the gate passes, continue. If not, recommend the alternative and stop.

---

## Phase 2: Intake

Collect three groups of facts. Run the live queries in parallel **only if** `VM_METRICS_URL` is set; otherwise
ask the user the same questions directly.

### 2a. Cardinality picture

What metric/set is the problem? How many series, driven by which labels?

```bash
# Top series by metric name (find the offenders)
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/tsdb?topN=20" | \
  jq '.data | {totalSeries, seriesCountByMetricName, seriesCountByLabelName}'

# For each suspect metric, see unique values per label
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/tsdb?topN=20&match[]=METRIC_NAME" | \
  jq '.data.labelValueCountByLabelName'
```

**Measure post-aggregation cardinality directly.** Once you have a candidate `by:` or `without:`,
run the equivalent grouping against current data instead of multiplying per-label unique-value
counts. The product-of-labels formula assumes every Cartesian combination of label values exists,
which is rarely true — and worse, can be **over-optimistic** when there are correlated labels or
labels you forgot to enumerate. The measured count is authoritative:

```bash
# Post-aggregation series count, using the labels you plan to KEEP.
# Replace <metric> and <kept_labels>. For counters use rate(...[5m]); for gauges use last_over_time.
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'query=count(sum(rate(<metric>[5m])) by (<kept_labels>))' \
  "$VM_METRICS_URL/api/v1/query" | jq '.data.result'

# Equivalent form using the labels you plan to DROP:
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'query=count(sum(rate(<metric>[5m])) without (<dropped_labels>))' \
  "$VM_METRICS_URL/api/v1/query" | jq '.data.result'
```

This gives the actual number of output series the rule will produce *on the current data*, which is
the right basis for the savings estimate in Phase 4d. Run it for each candidate rule before
committing to a config.

Interview questions if live queries are unavailable:

- Which metric or metric pattern is the problem?
- Approximate total series count for it?
- Which labels exist on it, and roughly how many unique values for each?
- Counter, gauge, or histogram?
- Scrape interval / push frequency?

When live queries aren't possible, treat the product-of-labels formula as an **upper bound** only,
and note explicitly to the user that the real post-aggregation count must be verified once data is
reachable.

### 2b. Collection topology

How do samples flow today? Sketch one of these:

```
A: app  -> vmagent -> remote write -> TimeSeries DB         (vmagent already in path)
B: app  -> remote write -> TimeSeries DB                    (no vmagent — must insert one)
C: app  -> [Prometheus | OTel | StatsD-exporter] -> remote write -> TimeSeries DB
D: app  -> load balancer -> N vmagents -> TimeSeries DB     (LB splits stream — dangerous for SA)
E: app  -> vmagent (HA pair / N replicas) -> TimeSeries DB  (multi-vmagent — dedup needed)
F: app  -> vmagent cluster (sharded) -> TimeSeries DB       (sharded by `-remoteWrite.shardByURL`)
```

The destination is shown as a generic "TimeSeries DB" — stream aggregation is a vmagent-side feature
and works with any remote-write-compatible backend (vmstorage/vmsingle, Prometheus, Cortex, Mimir,
Thanos receive, etc.). Caveats below that reference vmstorage dedup (`-dedup.minScrapeInterval`)
apply specifically when the backend is VictoriaMetrics; for other backends, replicate dedup at the
backend or accept that HA aggregation will write duplicates.

Interview questions:

- Is `vmagent` already in the path? If yes, how many replicas?
- Are samples behind a load balancer before reaching the aggregator?
- Is the same series fed by exactly one source instance, or by many (e.g., HA pairs, multi-region)?
- For K8s users: `VMAgent` CRD (vm-operator) or raw deployment?

### 2c. Consumer intent

What do downstream queries actually need?

- What resolution do dashboards/alerts query at? (e.g., `rate(...[5m])`, p99 over 5m)
- Do any consumers need per-pod / per-instance resolution for this metric? If "no, only service-wide"
  — that's the strongest signal that SA fits.
- Is the metric name referenced in alerting rules or recording rules? Renaming the metric after SA
  breaks those — track which queries must be updated.
- Are there separate destinations that want different aggregations? If yes, use **per-remote-write**
  configs (`-remoteWrite.streamAggr.config`); otherwise prefer global (`-streamAggr.config`).

---

## Phase 3: Decisions

For each metric or group, decide five things.

### 3a. Where to deploy vmagent

| Topology | Fits SA? | Notes |
|----------|----------|-------|
| **A. vmagent already in path, single replica** | Best. | Aggregation is exact — one vmagent sees every sample. |
| **B. No vmagent yet** | Insert vmagent **just before** the storage hop. | Adds one process, but you get aggregation + buffering + retries for free. |
| **C. Behind Prometheus/OTel collector** | Insert vmagent **between** the collector and remote write, or replace the collector with vmagent if scraping is acceptable. | Don't aggregate inside the collector unless it supports streaming aggregation. |
| **D. Behind a load balancer** | **Do not aggregate.** Each vmagent sees a fraction of samples → incomplete aggregates. | Shard traffic by `__name__` or labels first (`-remoteWrite.shardByURL.labels`), or terminate at a single aggregator. |
| **E. Multiple vmagent replicas (HA)** | Fits **only** for dedup-safe outputs (gauge-style: `min`, `max`, `avg`, `rate_*`, `increase*`, `last`, `quantiles`, `sum_samples`, etc.). All replicas must receive **identical** input, run **identical** config, and produce **identical** output labels — vmstorage dedup (`-dedup.minScrapeInterval`) collapses the duplicates. Do **not** tag replicas distinctly: that turns dedup-safe series into permanently doubled series at storage. Counter-style outputs (`total`, `total_prometheus`, `histogram_bucket`) cannot be HA'd this way — each replica's monotonic state diverges after restart. | See the High Availability section. |
| **F. Sharded vmagent fleet (single tier or tier-1 of a multi-tier topology)** | Fits if the aggregation respects the shard key. The shard label(s) — e.g., `instance`, `kubernetes_namespace`, `__name__` — must appear in every downstream rule's `by:` list, or equivalently must be **absent** from `without:`. Drop the shard key and each shard produces its own slice of the answer → silently wrong totals. | Common configurations: shard by `instance` and aggregate `by: [instance, method, status_code, le]`; shard by `kubernetes_namespace` and aggregate `by: [kubernetes_namespace, workload]`. If the shard key actively splits a series across shards (e.g., sharding by `pod` when you want to aggregate across pods), the topology can't satisfy the shard-key invariant — re-shard, or aggregate on the tier-1 vmagents before sharding. **Never shard by `le` (or `vmrange`) when aggregating histograms** — a single histogram's buckets must all land on the same aggregator. Sharding by `le` routes `le="0.1"`, `le="0.5"`, `le="+Inf"`, etc. for the same histogram to different shards; each shard sees only part of the bucket set, `histogram_quantile()` becomes incoherent, and quantiles silently drift. Shard histograms by a non-bucket label such as `instance`, `kubernetes_namespace`, or `__name__`. |

### 3b. Aggregation interval

Two constraints decide `interval`:

1. **Lower bound**: at least **2× the scrape/push interval** of the input. Anything less risks empty
   buckets when a single sample lands. Default to `2× scrape_interval` (so 30s for 15s scrapes).
2. **Upper bound**: no longer than the **shortest consumer query range**. If alerts use `rate(...[2m])`
   the interval must be ≤ 1m, ideally 30s. For dashboards with 5m windows, 1m is fine.

Other modifiers:

- **High delay / sample skew** → use a longer interval, or enable `enable_windows: true` (doubles
  memory but uses two-window state for accuracy). Critical for histograms.
- **Replacing a recording rule** → match the rule's evaluation interval (commonly 1m).
- **Downsampling for storage cost** → 1m–5m is typical; longer than 5m sacrifices interactive querying.

Default: **`interval: 30s`** for high-frequency app metrics, **`interval: 1m`** when replacing recording
rules, **`interval: 5m`** for pure downsampling.

### 3c. Output function

This is the most-frequently-wrong choice. Pick by metric kind first, then by what the consumer needs.

| Input kind | Consumer needs | Output | Notes |
|-----------|----------------|--------|-------|
| **Counter** | Sum of rate per output series (e.g., `sum(rate(req_total[5m]))`) | `rate_sum` | Result is a gauge of per-second rate. Query directly with `sum/avg_over_time` — do **not** take `rate()` again. |
| **Counter** | Increase per interval, as a counter for `rate()` later | `total` | Output is a monotonic counter resilient to per-source resets and series churn. Query with `rate()`. Use `total_prometheus` to skip the first sample per series. |
| **Counter** | Increase per interval, as a value (not a counter) | `increase` / `increase_prometheus` | Output is a gauge of the per-interval delta. |
| **Counter** | Average rate across input series | `rate_avg` | Use when you want mean-of-rates instead of sum-of-rates. |
| **Histogram bucket** (`*_bucket`, le-style) | `histogram_quantile()` | **`rate_sum`** + `enable_windows: true` | Recommended pattern. Bucket sets must match across aggregated series. |
| **Histogram bucket** | Total bucket counts as counter | `total` | Acceptable but more reset-sensitive than `rate_sum`. |
| **Gauge** | Latest value | `last` | Cheapest. Matches `last_over_time`. |
| **Gauge** | Sum across instances | `sum_samples` | E.g., total memory across pods. |
| **Gauge** | Min / Max / Avg | `min` / `max` / `avg` | Same name as the function. |
| **Gauge** | Distribution / percentiles | `quantiles(0.5, 0.9, 0.99)` or `histogram_bucket` | `quantiles` emits one output series per phi tagged with a `quantile="<phi>"` label. `histogram_bucket` returns VictoriaMetrics-style buckets you can later quantile-query — choose it when you need arbitrary quantiles later, `quantiles(...)` when the set is fixed. |
| **Gauge** | Count of unique values | `unique_samples` | Niche; for cardinality-style measurements. |
| **Either** | Sample count | `count_samples` / `count_series` | `count_samples` = how many points landed. `count_series` = how many distinct series existed in the interval. |

**The single most common mistake** is using `total` on a gauge or `sum_samples` on a counter — both
produce nonsense. **Counter → `total`/`rate_*`/`increase*`. Gauge → everything else.**

### 3d. `by` vs `without`

- Use **`without:`** when you know the labels to drop (e.g., `pod`, `instance`). The skill should
  prefer `without` — it's less error-prone if new labels appear later.
- Use **`by:`** when you know the exact set of labels to keep, and want a hard guarantee that any
  new label is dropped. Required when the input has many uncontrolled labels.
- Always keep **`le`** when aggregating histogram buckets.
- Always keep the labels your downstream queries already group by.
- Drop labels that are obviously high-cardinality and not consumed: `pod`, `instance`, `replica`,
  `container_id`. For **sharded** topologies (case F), keep the shard key. For
  **HA** topologies (case E), keep label sets *identical* across replicas — no per-replica tag.
- **`drop_input_labels` vs `without`/`by`**: both remove a label from the output. Prefer
  `drop_input_labels` (or the `-streamAggr.dropInputLabels` flag) when the label is **unbounded**
  (e.g., `request_id`, `trace_id`, `session_id`): it strips the label *before* dedup and state
  keying, so the aggregator never allocates per-value state for it — even transiently. Use
  `without`/`by` when the label has a reasonable cardinality but you don't want it on the output.

### 3e. Scale vmagent?

A single vmagent handles **millions of samples/sec** on modest hardware. Scale only when:

- CPU usage on the aggregating vmagent stays >70% with current load.
- `histogram_quantile(0.99, sum(rate(vm_streamaggr_flush_duration_seconds_bucket[1m])) by (vmrange))` approaches the aggregation interval.
- Memory pressure from many active output series (each output series ≈ small constant of RAM; with
  `enable_windows: true` it doubles).
- Input rate is sharded across many sources and consolidating in one vmagent is impractical.

When scaling:

- **Shard by series** (`-remoteWrite.shardByURL.labels`) so each input series lands on exactly one
  vmagent. Each shard produces a distinct slice of the output (different label values for the
  shard key); roll-up across shards happens at query time. See Phase 3a (case F).
- **HA replicas** (every replica sees every sample): use identical config and identical output
  labels; vmstorage dedup collapses duplicates. Only valid for dedup-safe outputs. See the High
  Availability section.

### 3f. How the aggregated output will be consumed

Two related decisions: what flows downstream alongside the aggregate, and what the aggregated metric
is called.

**Input retention** — what happens to the raw (unaggregated) samples after a rule matches them.
These are **command-line flags** (or per-remote-write equivalents), not YAML fields:

| User intent | Flag setting | Result |
|-------------|--------------|--------|
| **Aggregates only — drop matched raw** *(default steady state)* | neither flag | Aggregates written. Matched raw dropped. Unmatched-by-rule samples still written. Most common end state. |
| **Both raw and aggregates** *(rollout stage 2, or transition periods where consumers still need full resolution)* | `-streamAggr.keepInput=true` (or `-remoteWrite.streamAggr.keepInput=true`) | Aggregates + **all** raw samples written. Cardinality reduction is not yet realized — use temporarily. |
| **Aggregates only — drop everything that doesn't match the rules either** *(dedicated archive / long-term path)* | `-streamAggr.dropInput=true` (or `-remoteWrite.streamAggr.dropInput=true`) | Aggregates written. Matched and unmatched raw both dropped. Reach for this only when the destination should contain **nothing but aggregates** — e.g., a per-remote-write SA config aimed at a long-term store, with another (non-aggregating) remote-write carrying full-resolution data elsewhere. |

These flags compose with the rollout phases in 4c: typically start with `keepInput=true` during
verification, then remove it to reach the default steady state; only set `dropInput=true` if the
destination is purely an aggregate sink.

**Output metric naming** — by default the aggregated metric name is auto-generated and
self-describing:

```
<original_name>:<interval>[_by_<labels>][_without_<labels>]_<output>
```

with label lists sorted alphabetically, and a `quantile="<phi>"` label per output series when the
output is `quantiles(...)`. **Prefer the default** — it makes the aggregate distinguishable from the
raw metric at query time and prevents collisions if raw is still flowing.

Override only when there's a concrete reason:

- `keep_metric_names: true` (per-rule) — keeps the original metric name on the aggregated series.
  Valid **only** with a single entry in `outputs:`. Safe under the default behavior (matched raw is
  dropped from remote-write automatically). Risky if you've set `-streamAggr.keepInput=true`, since
  then aggregates and matched raw share the same name with different semantics — flip back to
  default before enabling `keep_metric_names`.
- `output_relabel_configs:` (per-rule) — full relabeling on the aggregated samples before they're
  written. Use it to strip the suffix, enforce a project naming convention, or rewrite labels:

  ```yaml
  output_relabel_configs:
    # Strip the auto-added ":interval_..._output" suffix
    - source_labels: [__name__]
      regex: '(.+):.+'
      target_label: __name__
      replacement: '$1'

    # Or enforce an "agg_" prefix
    - source_labels: [__name__]
      regex: '(.+)'
      target_label: __name__
      replacement: 'agg_$1'
  ```

  When you rename, plan the corresponding consumer migration (dashboards, alerts, recording rules) —
  see Phase 4c stage 4.

### 3g. Resolution vs. SA interval — replacing `sum(rate(X[5m]))`

A common request is "I have `sum(rate(req_total[5m]))` in my dashboards and alerts — please
pre-aggregate it." The naive mapping is to match the SA interval to the rate window:

```yaml
- match: 'req_total'
  interval: 5m            # too coarse — see below
  by: [<labels>]
  outputs: [rate_sum]
```

This produces **one datapoint every 5 minutes**. That resolution is often too coarse for alerting
(alerts evaluate every 30s–1m and need recent samples) and for graphs (5-minute step looks like a
staircase). The original `rate(...[5m])` also gave you a *rolling* 5m window evaluated at every
scrape; a 5m SA interval gives you a tumbling 5m bucket — those are not the same.

**Recommended default**: use a finer SA interval (typically `1m`) and reconstruct the rolling
smoothing at **query time** with `avg_over_time`:

```yaml
- match: 'req_total'
  interval: 1m
  by: [<labels>]
  outputs: [rate_sum]
```

Query rewrites:

```promql
# Original
sum(rate(req_total[5m]))

# After SA with interval: 1m, rate_sum  (rate_sum is already per-second, so don't rate() again)
sum(avg_over_time(req_total:1m_..._rate_sum[5m]))

# Original with grouping
sum by (route) (rate(req_total[5m]))

# After SA — use a subquery to apply avg_over_time after the sum-by
avg_over_time(
  (sum(req_total:1m_..._rate_sum) by (route))[5m:1m]
)
```

The `[5m:1m]` subquery means "evaluate the inner expression at 1m steps over a 5m window" — i.e.,
exactly the rolling-5m-window-every-1m behavior the original `rate(...[5m])` produced.

Trade-off table:

| SA `interval` | Samples written per 5m | When it fits |
|---------------|------------------------|--------------|
| `5m` | 1 | Backfill / long-term archive only. Acceptable when no consumer queries faster than 5m and a staircase graph is fine. |
| `1m` *(default for `[5m]` consumers)* | 5 | High-resolution graphs and alerts; `avg_over_time(...[5m])` at query time reproduces the original smoothing. |
| `30s` | 10 | Consumers use shorter windows (`[2m]`, `[1m]`) or zoom into sub-minute graphs. Often overkill. |

The same principle applies to `increase`, `increase_prometheus`, `rate_avg`, and gauge outputs
(`min`, `max`, `avg`, `sum_samples`): pick the SA interval based on the **fastest cadence any
consumer wants to query at**, not the largest range window the consumer uses. Reconstruct the range
window with the matching `*_over_time` wrapper at query time.

---

## Phase 4: Config + Rollout

Produce a single, self-contained plan that the user can read top-to-bottom and apply without
clicking through to docs. The expected output shape — adapt to the actual rule, omit sections that
don't apply:

> **Stream aggregation plan: `http_duration_p99`**
>
> | Decision | Choice | Why |
> |----------|--------|-----|
> | Placement | Existing tier-2 vmagent | Already in path; tier-1 shards by `kubernetes_namespace`, tier-2 aggregates within it |
> | Interval | `1m` | 2× scrape (15s); consumers use `[5m]` windows — reconstruct rolling avg at query time (Phase 3g) |
> | Output | `rate_sum` + `enable_windows: true` | Histogram → recommended pattern; consumers want p99 |
> | Grouping | `without: [pod, instance, path]` | Drop per-source + raw URL; keep `kubernetes_namespace` (shard key), `method`, `status_code`, `route`, `le` |
> | Input retention | default (matched raw dropped from remote write after cutover) | No consumer needs raw post-cutover |
> | Series before → after | ~5.3M → **~8.8K** (measured via `count(sum by (...)(rate(...[5m])))`) | ~600× reduction |
> | HA / sharding | Tier-2 has 2 HA replicas; identical config, identical labels, dedup at storage | Output is `rate_sum` (HA-safe). Do not tag replicas. |
>
> <details>
> <summary>Stream aggregation config — paste into <code>-streamAggr.config</code> (or <code>VMAgent.spec.streamAggrConfig.rules</code>)</summary>
>
> ```yaml
> - name: http_duration_p99
>   match: 'http_request_duration_seconds_bucket'
>   interval: 1m
>   enable_windows: true
>   without: [pod, instance, path]
>   outputs: [rate_sum]
> ```
> </details>
>
> <details>
> <summary>Rollout</summary>
>
> 1. Deploy config with `-streamAggr.keepInput=true` (or `streamAggrConfig.keepInput: true` on the CRD). Reload (`kill -SIGHUP …` or `/-/reload`).
> 2. Wait ≥1 hour, then run the cross-check query (verification block below). Aggregated p99 should track raw p99 within a few percent.
> 3. Remove `-streamAggr.keepInput=true`. Reload. Matched raw is now dropped from remote-write by default — cardinality reduction is realized.
> 4. Migrate dashboards / alerts to `http_request_duration_seconds_bucket:1m_without_instance_path_pod_rate_sum`. Suffix labels are sorted alphabetically.
> </details>
>
> <details>
> <summary>Verification queries</summary>
>
> ```promql
> # Cross-check: raw vs aggregated p99 (run during stage 2 with keepInput on)
> histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
>
> histogram_quantile(0.99,
>   sum by (le) (
>     avg_over_time(http_request_duration_seconds_bucket:1m_without_instance_path_pod_rate_sum[5m])
>   )
> )
>
> # Watch on vmagent /metrics
> # - histogram_quantile(0.99, sum(rate(vm_streamaggr_flush_duration_seconds_bucket{name="http_duration_p99"}[1m])) by (vmrange)) << 1m
> # - vm_streamaggr_counter_resets_total — flat (spikes = HA collision)
> # - count({__name__="http_request_duration_seconds_bucket:1m_without_instance_path_pod_rate_sum"}) ≈ 8800
> ```
> </details>

Adapt the structure for the actual scenario: a gauge with `quantiles(0.95)` won't need `enable_windows`; a downsampling rule replacing a recording rule may skip the cross-check (no raw to compare to). Drop the HA row if the deployment is single-replica.

### 4a. Generate the config

Template:

```yaml
- name: <descriptive_name>             # shows up in vm_streamaggr_* metrics
  match: '<series_selector>'           # e.g. '{__name__=~"http_request_.*"}'
  interval: <30s|1m|5m>
  # enable_windows: true               # REQUIRED for histograms; recommended when samples are delayed
  # staleness_interval: 2m             # default 2*interval; raise it if input is sporadic
  # ignore_first_sample_interval: 2m   # for total/increase/histogram_bucket after restart
  # ignore_old_samples: true           # if the stream contains backfilled / replayed data, is automatically applied when enable_windows are enabled
  without: [pod, instance, replica]    # or: by: [route, method, status_code, le]
  outputs: [rate_sum]                  # see output picker above
  # keep_metric_names: true            # only with a single output; drops the ":interval_..." suffix
  # drop_input_labels: [container_id]  # drops labels *before* dedup + aggregation
  # input_relabel_configs: [...]       # rare; transform labels before aggregating
  # output_relabel_configs: [...]      # rare; e.g. strip the auto-added suffix
```

**Do not** put `keep_input` or `drop_input` inside the YAML — those are command-line flags
(`-streamAggr.keepInput`, `-streamAggr.dropInput`, plus per-remote-write variants). Several common
guides get this wrong.

Chose `name` field to reflect original metric name and aggregation output, but keep it simple enough that's easy to understand.

### 4b. Where the config lives

| Mechanism | Use when |
|-----------|----------|
| `-streamAggr.config` | One global config replicated to all `-remoteWrite.url` destinations. **Default choice.** Aggregation runs once. |
| `-remoteWrite.streamAggr.config` (per URL) | Different destinations need different aggregates (e.g., long-term store gets aggregated only). Aggregation runs per destination — more CPU. |
| vmsingle `-streamAggr.config` | Single-node setup; same engine, same YAML. |

### 4c. Phased rollout

1. **Stage 1 — observe**. Deploy with input retained, so both raw and aggregated land in storage:
   - Don't set `-streamAggr.dropInput` (default keeps unmatched + writes aggregates).
   - Set `-streamAggr.keepInput=true` to **also** write the matched raw samples. This lets you
     compare raw vs aggregated queries side-by-side.
2. **Stage 2 — verify** (see Phase 5). Aggregated output should match the corresponding
   `sum(rate(...))` / `histogram_quantile(...)` over raw for at least an hour, including across a
   vmagent restart if possible.
3. **Stage 3 — cut over**. Remove `-streamAggr.keepInput`. That's it — the cardinality reduction is
   realized at this point. The default SA behavior writes aggregates and **drops matched raw
   samples** from the remote-write output (only the unmatched-by-rule samples continue to flow as
   raw). You do **not** need to drop the raw metric at the scrape side; in fact you must **not**,
   because vmagent's pipeline is `scrape → relabel → dedup → stream aggregation → remote write`, so
   a scrape-side drop removes the input the aggregator needs and the rule produces nothing.

   Optionally set `-streamAggr.dropInput=true` only if you also want to drop all *unmatched-by-rule*
   samples (rare; appropriate when this remote-write destination is dedicated to aggregates and
   another remote-write carries the full-resolution data). See Phase 3f for the three input-retention
   modes.
4. **Stage 4 — migrate consumers**. Update dashboards / alerts to the new metric name (with the
   auto-added suffix). The suffix format is `:<interval>[_by_<labels>][_without_<labels>]_<output>`
   where **both** label lists are sorted alphabetically — `without: [pod, instance, path]` yields
   `_without_instance_path_pod_`; `by: [function, region, cold_start]` yields
   `_by_cold_start_function_region_`. For `outputs: [quantiles(0.5, 0.99)]` each output series also
   carries a `quantile="<phi>"` label. If you'd rather keep the original metric name, set
   `keep_metric_names: true` (valid only with a single output), and make sure raw is fully dropped or
   you'll have two series with the same name and different semantics.

Reload without restart:

```bash
kill -SIGHUP $(pidof vmagent)
# or
curl -X POST http://vmagent:8429/-/reload
```

### 4d. Estimate the savings

For each rule, give the user two numbers:

- **Series before** (current): from `seriesCountByMetricName` in TSDB status, or user-reported.
- **Series after** (measured): the count returned by the `count(sum(rate(<metric>[5m])) by (<kept_labels>))`
  query in Phase 2a, run against current data. This is the authoritative number — the rule will
  produce roughly this many output series on the current data.

Only fall back to the product-of-labels formula when live data isn't reachable, and label it as an
upper bound:

```
output_series ≤ Π(unique values of each label in `by`, including __name__)
```

The product overestimates when label values are correlated (most routes don't return every status
code) and can also *under*estimate when there are labels the user didn't enumerate — both reasons
to prefer the measured count.

Sanity check: if the measured after-aggregation count is **larger** than before, the `by`/`without`
is wrong — you're keeping labels that produce more unique combinations than expected.

---

## Phase 5: Verify

After the rule is live, run these checks. Use them in stage 2 (with raw retained) and again in
stage 3.

### 5a. Stream aggregation internal metrics

Check metrics exposed by vmagent that does the aggregation (or check them on the vmagent [Grafana dashboard](https://grafana.com/grafana/dashboards/12683-victoriametrics-vmagent/) in `Stream aggregation` section):

| Metric                                            | What it tells you                                                                                                                                                                                                                                           |
|---------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `vm_streamaggr_matched_samples_total{name="..."}` | Input samples matched by the rule. Should match expected scrape rate × series count.                                                                                                                                                                        |
| `vm_streamaggr_output_samples_total{name="..."}`  | Aggregated samples emitted. Roughly `output_series / aggregation_interval`.                                                                                                                                                                                 |
| `vm_streamaggr_flush_duration_seconds_bucket`     | Time spent flushing each interval. Can be calculated as `histogram_quantile(0.99, rate(vm_streamaggr_flush_duration_seconds_bucket[5m]))` to get 99th percentile. Should be well below `interval`. If close to interval, scale vmagent or raise `interval`. |
| `vm_streamaggr_ignored_samples_total`             | Samples dropped due to different reasons. Spikes in `too_old` reasin may indicates upstream delays. See also `vm_streamaggr_samples_lag_seconds_bucket` for the delivery lag.                                                                               |
| `vm_streamaggr_counter_resets_total`              | Counter resets observed. **Sudden spike** = duplicate or colliding input samples; check for upstream issues or a misconfigured topology (e.g., HA replicas with a counter-style output, see High Availability section).                                     |

### 5b. Cross-check aggregated vs raw (stage 2 only)

For a counter aggregated with `rate_sum`:

```promql
# raw
sum by (route, method, le) (rate(http_request_duration_seconds_bucket[5m]))

# aggregated (rate_sum is already a per-second rate — sum it, don't rate it again)
sum by (route, method, le) (http_request_duration_seconds_bucket:30s_without_pod_instance_rate_sum)
```

The two should track within a few percent. If they diverge sharply, suspect:

- Multi-vmagent collision (Phase 3a, case E).
- Behind a load balancer (Phase 3a, case D).
- Mismatched `dedup_interval` vs storage `-dedup.minScrapeInterval`.
- For histograms: sample delays — enable `enable_windows` and/or raise `interval`.

For histograms via `rate_sum`:

```promql
# raw p99
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))

# aggregated p99
histogram_quantile(0.99, sum by (le) (avg_over_time(http_request_duration_seconds_bucket:30s_without_pod_instance_rate_sum[5m])))
```

### 5c. Sanity checks

- Output series count from `count({__name__="<aggregated_name>"})` ≈ your Phase 4d estimate.
- No alerts about `histogram_quantile(0.99, sum(rate(vm_streamaggr_flush_duration_seconds_bucket[1m])) by (vmrange))` approaching interval.
- For `total`/`increase` outputs: counter is monotonic; resets only on vmagent restart (which is
  expected unless `flush_on_shutdown: true` is set).

---

## High Availability

Running multiple vmagent replicas for resilience is supported, but only under specific conditions —
stream aggregation maintains state in the aggregator process, and that state cannot be replicated
across replicas.

### The mechanism

Multiple replicas produce the **same** output series — identical label sets — and let
vmstorage's deduplication collapse the duplicates. This works **only** when:

1. Every replica receives **identical input** — same scrape targets, or fan-out (not round-robin)
   remote-write. A round-robin load balancer in front of HA replicas splits the stream, which both
   defeats HA *and* produces incomplete aggregates per replica.
2. Every replica runs **identical aggregation configuration**.
3. Every replica produces output samples with **identical labels** (no per-replica tagging — see
   below).
4. vmstorage has `-dedup.minScrapeInterval` set (usually equal to the aggregation `interval`); the
   per-rule `dedup_interval` should match.
5. The chosen aggregation output is dedup-safe (next section).

**Do not** tag HA replicas with distinct labels (`-remoteWrite.label=vmagent=A`, `=B`). Distinct
labels make the series genuinely different — vmstorage won't dedup, you pay double the storage, and
the consumer must `sum without (vmagent)` everywhere. The "tag each replica" pattern is for
*sharded* topologies (case F), where each replica sees a disjoint slice of inputs and must keep
them apart, not for HA where replicas see the same inputs.

### HA-safe vs unsafe outputs

| Output | HA-safe? | Why |
|--------|---------|-----|
| `min`, `max`, `avg`, `last`, `sum_samples`, `count_samples`, `count_series`, `unique_samples`, `stddev`, `stdvar`, `quantiles(...)` | ✅ | Each interval's value is computed independently from samples seen in that interval. Two replicas that see the same input converge to the same value → dedup is clean. |
| `rate_sum`, `rate_avg`, `increase`, `increase_prometheus` | ✅ (with caveat) | Output is a **per-interval gauge** of rate or delta, not a monotonic counter. Internal per-series state can briefly diverge after one replica restarts (until the next staleness window), but the output values converge. |
| `total`, `total_prometheus` | ❌ | Output is a **monotonically increasing counter** held in aggregator memory. After one replica restarts, its output resets to 0 while the other's keeps climbing. Dedup picks one sample per (series, timestamp) — with two divergent counter streams emitting at the same series, the consumer sees an alternating sequence, and `rate()` reads the backward steps as counter resets, producing visible jumps and spikes. There is no clean way to dedupe two divergent monotonic counters. |
| `histogram_bucket` | ❌ | Per-bucket counters accumulate the same way `total` does. Same divergence problem. |

For consumers that insist on a counter shape (e.g., legacy alerts using `rate(...[5m])`), the
HA-safe options are:

- Switch the aggregation to `rate_sum` and update the query (`rate_sum` is already a per-second
  rate — sum/avg it instead of taking `rate()`).
- Switch to `increase` and use `increase`-style queries.
- Run a single aggregator (active/passive failover) instead of true HA — accept brief gaps during
  failover rather than divergent monotonic state.

### HA vs sharding — different patterns, don't combine on the same dimension

- **Sharded** (case F): each replica sees a *disjoint slice* of inputs. Each emits distinct output
  series — either by keeping the shard key in `by:` (preferred — roll up at query time), or by
  tagging with a unique label. Different replicas produce different values intentionally.
- **HA** (case E): every replica sees the *same* inputs and emits the *same* output labels.
  Different replicas produce equal values that vmstorage dedup collapses.

A tier-1-sharded + tier-2-HA topology is valid: tier-1 shards by `instance`; each tier-1 shard
fans out to two tier-2 HA replicas that both see the same shard's stream and emit identical
output. The shard key (`instance`) appears in `by:` on tier-2; HA replicas at tier-2 are otherwise
configured identically.

---

## Risk Callouts (tied to output choice)

Surface these **only** when the chosen output triggers them — don't dump them all unconditionally.

### When output ∈ {`total`, `total_prometheus`, `increase`, `increase_prometheus`, `rate_avg`, `rate_sum`, `histogram_bucket`}

- **Staleness**: per-series state is reset after `staleness_interval` (default `2 × interval`) without
  new samples. For sporadic inputs (Lambda, cron jobs, batch workers), raise `staleness_interval` or
  values will spike on re-appearance. See [Staleness](https://docs.victoriametrics.com/victoriametrics/stream-aggregation/#staleness).

### When inputs are sporadic (any output, especially gauges)

- Even for outputs without per-series state (e.g., `quantiles`, `last`, `sum_samples`), a long gap
  between samples means the corresponding output series is *missing* for those intervals — gauges in
  dashboards will have gaps. Raise `staleness_interval` to cover the maximum expected silence, or
  use `last_over_time(<aggregated>[<gap>])` at query time to paper over short absences.
- **First sample after restart**: `total`/`increase` assume new series start at 0, so the first
  sample after a restart looks like a huge increase. Set `ignore_first_sample_interval` or use
  `*_prometheus` variants to skip the first sample.
- **Counter resets** (`vm_streamaggr_counter_resets_total` ticking up): duplicate samples or
  collision between vmagent replicas. Either dedup before aggregation (`dedup_interval`) or ensure
  each output series is produced by exactly one aggregator.

### When aggregating histograms (any output)

- **Bucket consistency**: histograms can only be aggregated if their `le` (or `vmrange`) labels are
  identical across input series. Inconsistent bucket boundaries → silently wrong quantiles.
- **Sample delay sensitivity**: histograms are a logical group of series that must update together.
  Misaligned samples → wrong quantiles. Mitigations: **`enable_windows: true`**, longer `interval`,
  ensure vmagent + delivery pipeline have headroom (no queue accumulation).
- **+Inf bucket**: must exist on inputs; `histogram_quantile` requires it.
- **Never shard by `le` (or `vmrange`)**: in a sharded vmagent topology (case F), the shard key must
  not be the bucket label. A histogram is a logical group of series differing only in `le` — all of
  those buckets must land on the same aggregator so it can produce a coherent bucket set. Sharding
  by `le` splits one histogram's buckets across shards; each shard then emits a partial bucket set,
  and `histogram_quantile()` over the merged result is silently wrong. Pick a non-bucket label
  (`instance`, `kubernetes_namespace`, `__name__`, etc.) as the shard key, and keep `le` in every
  aggregation rule's `by:` list.

### When running multiple vmagent replicas

- **HA topology** (every replica sees every sample): identical input + identical config + identical
  output labels → vmstorage dedup collapses duplicates. Don't tag replicas. Only works for
  dedup-safe outputs — see the High Availability section.
- **Sharded topology** (each replica owns a disjoint slice — case F): keep the shard key in `by:`,
  or, if you can't, tag each replica with a unique label and re-aggregate at query time with
  `sum without (vmagent) (...)`. See [cluster mode](https://docs.victoriametrics.com/victoriametrics/stream-aggregation/#cluster-mode).
- Round-robin LBs in front of replicas are wrong for **both** patterns: HA loses dedup safety
  (each replica sees a partial stream), and sharded loses determinism. Use deterministic
  `-remoteWrite.shardByURL.labels=...` for sharding, or fan-out (every replica receives every
  sample) for HA.

### When dedup is enabled

- `dedup_interval` must equal storage `-dedup.minScrapeInterval`. Mismatch → raw query results
  (e.g. `sum(rate(...))`) won't match the aggregated metric. See [common mistakes](https://docs.victoriametrics.com/victoriametrics/stream-aggregation/#use-different-deduplication-intervals-on-storage-and-vmagent).

---

## Kubernetes / VictoriaMetrics Operator

Stream aggregation config is exposed on the `VMAgent` CRD via `streamAggrConfig` (global) or
`remoteWrite[].streamAggrConfig` (per destination).

<details>
<summary>VMAgent CRD — global stream aggregation</summary>

The vm-operator exposes `streamAggrConfig` with camelCase fields. `keepInput`/`dropInput` are
top-level fields here (mirroring the `-streamAggr.keepInput` / `-streamAggr.dropInput` flags), not
fields inside individual rules. Field spelling depends on operator version — confirm against the
[VMAgent CRD reference](https://docs.victoriametrics.com/operator/api/#vmagent) if unsure.

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMAgent
metadata:
  name: vmagent
spec:
  replicaCount: 2                   # HA: both replicas see every sample; identical config below
  # Do NOT add a per-replica externalLabel for HA — it defeats vmstorage dedup. See HA section.
  extraArgs:
    streamAggr.dedupInterval: "30s" # match vmstorage -dedup.minScrapeInterval
  streamAggrConfig:
    keepInput: true                 # stage 2 — top-level, NOT inside a rule. Remove after verifying.
    rules:
      - match: 'http_request_duration_seconds_bucket'
        interval: 30s
        enable_windows: true
        without: [pod, instance]
        outputs: [rate_sum]          # HA-safe (per-interval rate, not monotonic counter)
  remoteWrite:
    - url: http://vmsingle.monitoring.svc:8429/api/v1/write
```
</details>

<details>
<summary>VMAgent CRD — per-remote-write aggregation</summary>

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMAgent
metadata:
  name: vmagent
spec:
  remoteWrite:
    - url: http://vmstorage-long-term.monitoring.svc:8429/api/v1/write
      streamAggrConfig:
        dropInput: true              # send ONLY aggregates to long-term store
        rules:
          - match: '{__name__=~".+"}'
            interval: 5m
            outputs: [last, max, min, count_samples]
    - url: http://vmstorage-hot.monitoring.svc:8429/api/v1/write
      # raw, full-resolution data to the hot store
```
</details>

<details>
<summary>Two-tier topology — tier-1 shards, tier-2 aggregates (shard key = <code>instance</code>)</summary>

Tier-1 vmagents shard by `instance` to tier-2 aggregating vmagents. Each tier-2 instance owns a
disjoint slice of `instance` values, so it sees every sample for those instances and can produce
correct aggregates — **as long as** `instance` is preserved in `by:`.

Tier-1 (sharding only, no aggregation):

```bash
vmagent-tier1 \
  -remoteWrite.url=http://vmagent-tier2-0:8429/api/v1/write \
  -remoteWrite.url=http://vmagent-tier2-1:8429/api/v1/write \
  -remoteWrite.url=http://vmagent-tier2-2:8429/api/v1/write \
  -remoteWrite.shardByURL=true \
  -remoteWrite.shardByURL.labels=instance
```

Tier-2 (aggregation that respects the shard key):

```yaml
# tier2-stream-aggr.yaml
- match: 'http_request_duration_seconds_bucket'
  interval: 30s
  enable_windows: true
  by: [instance, method, status_code, route, le]   # `instance` MUST stay — it's the shard key
  outputs: [rate_sum]
```

```bash
vmagent-tier2 \
  -remoteWrite.url=http://vmstorage:8429/api/v1/write \
  -streamAggr.config=/etc/vmagent/tier2-stream-aggr.yaml
```

If you also want a per-service rollup (without `instance`), do it at **query time** —
`sum without (instance) (http_request_duration_seconds_bucket:30s_by_...:rate_sum)` — not in a
second aggregation rule on tier-2, because each tier-2 only has its slice of instances.
</details>

<details>
<summary>Bare metal / Docker — command-line flags</summary>

```bash
vmagent \
  -remoteWrite.url=http://vmsingle:8429/api/v1/write \
  -streamAggr.config=/etc/vmagent/stream-aggr.yaml \
  -streamAggr.dedupInterval=30s \
  -streamAggr.keepInput=true                        # stage 2 only
```

For HA (every replica scrapes the same targets, dedup-safe output only): omit any per-replica label
— identical labels are required for vmstorage dedup to collapse duplicates. For *sharded* topologies
where each replica owns a disjoint slice (case F), add a per-replica label *only if* the shard key
isn't already preserved in `by:`:

```bash
  -remoteWrite.label=vmagent=$HOSTNAME   # sharded ≠ HA; do NOT use this for HA
```
</details>

---

## Worked Example

User: "600 pods, `http_request_duration_seconds_bucket` exploding, labels `pod, instance, method, path,
status_code, le, route`, 40 routes, 10 le buckets, vmagent already in path, only need service-wide p99."

Decisions:

| Decision | Choice | Why |
|----------|--------|-----|
| Gate | passes — vmagent in path, lose-per-pod is acceptable | |
| Interval | `30s` | 2× the 15s scrape interval; matches 5m query windows. |
| Output | `rate_sum` + `enable_windows: true` | Histogram bucket → recommended pattern; consumer is `histogram_quantile`. |
| `without` | `[pod, instance, path]` (assuming `route` is the normalized form) | Drop everything not needed; keep `method`, `status_code`, `route`, `le`. |
| Placement | Existing vmagent | Already in path. Confirm only one replica or use HA tagging. |
| Scale | No | Single rule; current vmagent fine. |

Estimate: `4 methods × 5 status × 40 routes × 11 buckets (incl. +Inf) ≈ 8.8K series` vs `600 pods × 8.8K ≈ 5.3M` raw → ~600× reduction.

Config:

```yaml
- name: http_duration_p99
  match: 'http_request_duration_seconds_bucket'
  interval: 30s
  enable_windows: true
  without: [pod, instance, path]
  outputs: [rate_sum]
```

Rollout: enable `-streamAggr.keepInput=true`, deploy, verify with the cross-check query in Phase 5b
for one hour, then drop the flag. Once `keepInput` is gone, matched raw is no longer written to
remote storage by default — the cardinality reduction is realized. Do not drop the metric at the
scrape side; that would remove the input the aggregator depends on.

Consumer query update — note the suffix sorts labels alphabetically (`instance, path, pod`):

```promql
# Before
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))

# After
histogram_quantile(0.99,
  sum by (le, route) (
    avg_over_time(http_request_duration_seconds_bucket:30s_without_instance_path_pod_rate_sum[5m])
  )
)
```

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Putting `keep_input` / `drop_input` in the YAML | Those are command-line flags (`-streamAggr.keepInput`, `-streamAggr.dropInput`, or per-remote-write variants). |
| Using `total` on a gauge | `total` is for counters. Use `last`/`avg`/`sum_samples` for gauges. |
| Using `sum_samples` on a counter | Sums raw counter values — meaningless. Use `total`, `increase`, or `rate_sum`. |
| Querying `rate_sum` output with `rate()` | `rate_sum` is already a per-second rate. Sum/avg it, don't rate it. |
| Querying `total` output without `rate()` | `total` is a monotonic counter — use `rate()` or `increase()`. |
| Interval shorter than scrape interval | Empty buckets, jittery output. Set `interval ≥ 2× scrape_interval`. |
| Tagging HA replicas with a distinct `vmagent=...` label | Defeats vmstorage dedup → permanently doubled series at storage. For HA, replicas must emit *identical* labels; dedup collapses them. The "tag each replica" pattern is for sharded topologies, not HA. |
| Running HA replicas with a `total` or `total_prometheus` output | Counter state is in-process and diverges after a single replica restart → consumer sees jumps. Switch to `rate_sum` or `increase`, or run a single aggregator. |
| HA replicas behind a round-robin load balancer | Each replica sees a partial stream → aggregates are incomplete AND can't dedup. Use fan-out (every replica receives every sample) or deterministic sharding. |
| Aggregator behind a round-robin load balancer | Each vmagent sees a slice → incomplete aggregates. Shard deterministically by labels (`-remoteWrite.shardByURL.labels`) first, or terminate at one aggregator. |
| Sharded vmagents that drop the shard key in `without:` (or omit it from `by:`) | Each shard produces a partial aggregate over its slice of inputs; outputs from different shards collide on the same series → silently wrong totals. Keep the shard key in `by:` on every downstream rule, and do any further roll-up at query time. |
| Sharding histograms by `le` (or `vmrange`) | Splits one histogram's buckets across shards; each shard emits a partial bucket set; `histogram_quantile()` over the merged result is silently wrong. Shard histograms by a non-bucket label (`instance`, `kubernetes_namespace`, `__name__`) and keep `le` in `by:`. |
| `dedup_interval` differs from storage `-dedup.minScrapeInterval` | Raw vs aggregated query results diverge. Make them equal. |
| Aggregating histograms without `enable_windows` | Misaligned samples → wrong quantiles. Set `enable_windows: true`. |
| Renaming output to original metric name, but raw still flows | Two different series with the same name. Either drop input (`-streamAggr.dropInput`) or keep the suffix. |
| One aggregation rule per recording rule | Each rule scans every sample. Merge rules with shared `interval` and `by`/`without` using a list-form `match:`. |
| Setting `staleness_interval` too low for sporadic inputs | State resets between samples → wrong totals. Raise it to cover the expected gap. |
| `keep_metric_names: true` with multiple outputs | Not allowed — only valid with a single output. |
| Forgetting to update alert/recording rules | Old rules query a metric that no longer exists (or, worse, exists but is now empty raw). |

---

## Quick Reference

```yaml
# Skeleton — start here, fill in `match`, `interval`, `without`/`by`, `outputs`.
- name: <name>
  match: '<selector>'
  interval: 30s
  without: [pod, instance]
  outputs: [rate_sum]              # see output picker
  # enable_windows: true           # histograms; delayed inputs
  # dedup_interval: 30s            # match storage dedup
  # staleness_interval: 4m         # for sporadic inputs
```

**Output picker (90% of cases):**
- Counter, want sum-of-rate: `rate_sum`
- Counter, want monotonic counter: `total`
- Histogram bucket: `rate_sum` + `enable_windows: true`
- Gauge, latest: `last`
- Gauge, sum across sources: `sum_samples`
- Gauge, percentiles: `quantiles(0.5, 0.9, 0.99)`

**Decision shortcuts:**
- Interval = max(2 × scrape_interval, shortest consumer window / 2)
- Drop `pod`/`instance` unless per-source is consumed
- HA vmagents: identical input + identical config + identical output labels → vmstorage dedups. **Don't tag** replicas. HA-safe outputs only (no `total`/`total_prometheus`/`histogram_bucket`).
- Sharded vmagents: keep the shard key in `by:`, or tag each replica and roll up at query time.
- Behind a round-robin LB: stop. Use deterministic sharding (`-remoteWrite.shardByURL.labels`) or fan-out.
- Replacing recording rule: set `interval` = rule's evaluation interval, use a list-form `match:` to fold many rules into one config entry.
