---
name: victoriametrics-cardinality-analysis
description: >
  Analyze VictoriaMetrics time series cardinality to find optimization opportunities — unused metrics,
  high-cardinality labels, problematic label values, histogram bloat. Produces actionable report with
  relabeling and stream aggregation recommendations. Use whenever the user mentions cardinality analysis,
  series reduction, unused metrics, high cardinality labels, TSDB optimization, storage cost reduction,
  metric cleanup, too many time series, or wants to reduce cardinality. Also trigger when discussing
  relabeling strategies, streaming aggregation opportunities, or "which metrics can we drop".
allowed-tools: Bash(curl:*)
---

# VictoriaMetrics Cardinality Analysis

Systematic cardinality analysis for VictoriaMetrics. Collects TSDB status, metric usage stats, and label
value patterns, then produces a structured report with specific relabeling and stream aggregation configs
the user can apply directly.

The goal is to find the highest-impact optimization opportunities — metrics nobody queries, labels that
explode cardinality for no monitoring value, and patterns that indicate data hygiene problems (error
messages as labels, SQL text as labels, UUIDs as labels).

## Environment

| Variable | Purpose |
|----------|---------|
| `$VM_METRICS_URL` | vmselect base URL (includes tenant path, e.g. `.../select/0/prometheus`) |
| `$VM_AUTH_HEADER` | Auth header for API calls |

All curl commands use conditional auth:

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} "$VM_METRICS_URL/..."
```

## Workflow

### Phase 1: Data Collection

Spawn 3 subagents in a **single response** to collect data in parallel. Each subagent prompt must
include the curl auth pattern and environment variable references above.

If the user specified a scope (job, namespace, metric prefix), pass it as `match[]` parameter to
TSDB status queries and as series selectors to label queries.

---

#### Subagent 1: TSDB Overview

**Agent name**: `cardinality-tsdb` | **Description**: "Collect TSDB cardinality stats"

**Query 1 — Yesterday's series (captures recently churned series):**

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/tsdb?topN=50&date=$(date -d 'yesterday' +%Y-%m-%d)" | jq '.data'
```

Queries yesterday's stats — broader than today (includes series that may have already churned) without scanning the entire TSDB.

**Query 2 — Today's active series:**

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/tsdb?topN=50" | jq '.data'
```

**Query 3 — Focus on known high-cardinality labels:**

```bash
for label in pod instance container path url user_id request_id session_id trace_id le name; do
  echo "=== focusLabel=$label ===" && \
  curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
    "$VM_METRICS_URL/api/v1/status/tsdb?topN=20&focusLabel=$label" | \
    jq --arg l "$label" '{label: $l, focus: .data.seriesCountByFocusLabelValue}'
done
```

**Return**: All raw JSON preserving structure. Include `totalSeries`, `totalLabelValuePairs`,
`seriesCountByMetricName`, `seriesCountByLabelName`, `seriesCountByLabelValuePair` from each query.

---

#### Subagent 2: Metric Usage Stats

**Agent name**: `cardinality-usage` | **Description**: "Find unused and rarely-queried metrics"

**Query 1 — Never-queried metrics:**

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/metric_names_stats?le=0&limit=500" | jq '.'
```

**Query 2 — Rarely-queried metrics (≤5 total queries):**

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/metric_names_stats?le=5&limit=500" | jq '.'
```

**Query 3 — Stats overview (tracking period):**

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/metric_names_stats?limit=1" | \
  jq '{statsCollectedSince: .statsCollectedSince, statsCollectedRecordsTotal: .statsCollectedRecordsTotal}'
```

If the endpoint returns an error, `storage.trackMetricNamesStats` may not be enabled on vmstorage.
Note this in the return and proceed — the analysis can still work with TSDB status data alone.

**Query 4 — Cross-check: are "unused" metrics referenced in alerting rules?**

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/rules" | jq '[.data.groups[].rules[].query]'
```

Extract metric names from rule queries. Any "unused" metric that appears in an alert/recording rule
is NOT safe to drop — it's queried indirectly.

**Return**: Unused metrics with cross-reference against alert rules. Flag each as:

- **safe to drop**: never queried AND not in any rule
- **used by rules only**: never queried by dashboards but referenced in rules — verify intent
- **rarely used**: low query count, may be accessed infrequently (e.g., monthly reports)

---

#### Subagent 3: Label Pattern Inspection

**Agent name**: `cardinality-labels` | **Description**: "Inspect label values for problematic patterns"

All data comes from the TSDB status endpoint — do NOT use `/api/v1/labels` or `/api/v1/label/.../values`.

**Query 1 — Label cardinality overview (unique value counts + series counts):**

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/tsdb?topN=50" | \
  jq '{labelValueCountByLabelName: .data.labelValueCountByLabelName, seriesCountByLabelName: .data.seriesCountByLabelName}'
```

`labelValueCountByLabelName` returns labels sorted by unique value count (replaces per-label `/values` counting).
`seriesCountByLabelName` shows how many series each label appears in.

**Query 2 — Sample values for high-cardinality labels via focusLabel:**
For each label with >100 unique values from Query 1, fetch sample values:

```bash
for label in <top labels from Query 1>; do
  echo "=== focusLabel=$label ===" && \
  curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
    "$VM_METRICS_URL/api/v1/status/tsdb?topN=20&focusLabel=$label" | \
    jq --arg l "$label" '{label: $l, topValues: .data.seriesCountByFocusLabelValue}'
done
```

`seriesCountByFocusLabelValue` returns label values sorted by series count — use the value names to detect problematic patterns.

**Query 3 — High-cardinality label-value pairs:**

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/tsdb?topN=50" | \
  jq '.data.seriesCountByLabelValuePair'
```

Shows which specific `label=value` pairs contribute the most series.

**Pattern detection** — classify label values from focusLabel samples:

| Pattern | Regex hint | Indicates |
|---------|-----------|-----------|
| UUIDs | `[0-9a-f]{8}-[0-9a-f]{4}-` | Request/session/trace IDs as labels |
| IP addresses | `\d+\.\d+\.\d+\.\d+` | Per-client or per-pod IP tracking |
| Long strings (>50 chars) | length check | Error messages, SQL, stack traces |
| SQL keywords | `SELECT\|INSERT\|UPDATE\|DELETE\|FROM\|WHERE` | Query text stored as label |
| URL paths with IDs | `/api/.*/[0-9a-f]+` | Unsanitized HTTP paths |
| Timestamps | epoch or ISO8601 | Time values as labels (unbounded) |
| Stack traces | `at .*\.(java\|go\|py):` | Error details as labels |

**Return**: Table of labels sorted by unique value count, with detected pattern, sample values from focusLabel, and series impact.

---

### Phase 2: Analysis

After all subagents return, compile and classify findings. This is the analytical core — apply
judgment, not mechanical filtering.

#### Category 1: Unused Metrics (Quick Wins)

Cross-reference metric usage stats with TSDB series counts:

- **Drop candidates**: `queryRequestsCount=0`, not in any alert/recording rule, >100 series
- **Verify candidates**: `queryRequestsCount=0` but referenced in rules — check if rule is still needed
- **Low-priority**: `queryRequestsCount≤5` with few series — not worth the config churn

Sort by series count descending — the biggest unused metrics are the biggest wins.

#### Category 2: High-Cardinality Labels

Labels with excessive unique values that drive series explosion:

| Label pattern | Assessment | Typical remedy |
|--------------|------------|----------------|
| `user_id`, `customer_id`, `account_id` | Should NEVER be metric labels — belongs in logs/traces | Drop label |
| `request_id`, `session_id`, `trace_id`, `span_id` | Correlation IDs — never metric labels | Drop label |
| `error`, `error_message`, `reason`, `status_message` | Unbounded strings | Drop label or replace with error code |
| `sql`, `query`, `command`, `statement` | Query text in labels — unbounded | Drop label |
| `path`, `url`, `uri`, `endpoint` | Unbounded if not sanitized | Relabel to normalize, or stream aggregate without |
| `pod`, `container` | Normal for k8s but high churn | Stream aggregate without, if per-pod not needed |
| `instance` | Normal for node metrics, wasteful for app metrics | Stream aggregate without for app-level metrics |
| `le` (histogram buckets) | Fine-grained buckets multiply every label combination | Reduce bucket count |

For each finding, estimate impact: `(series with this label) - (series without) ≈ series saved`.

#### Category 3: Histogram Bloat

Check metrics ending in `_bucket`:

- How many unique `le` values?
- Each additional bucket multiplies series by (number of label combinations)
- Look for histograms where most buckets are empty or redundant

#### Category 4: Series Churn

Compare yesterday's stats vs today:

- Ratio >3:1 suggests significant churn from pod restarts, deployments, short-lived jobs
- Not directly fixable via relabeling, but indicates opportunity for `dedup_interval` or
  `-search.maxStalenessInterval` tuning

---

### Phase 3: Report

Compile into a structured report. **Every finding must include impact estimate and specific remedy config.**

Use this template:

```markdown
## VictoriaMetrics Cardinality Report — <date>

### Overview
| Metric | Value |
|--------|-------|
| Total active series (today) | X |
| Total series (yesterday) | X |
| Churn ratio (yesterday / today) | X:1 |
| Unique metric names | X |
| Stats tracking since | <date> |

### 1. Unused Metrics
**Potential savings: ~X series (Y% of total)**

| Metric | Series | Last Queried | In Alert Rules | Action |
|--------|--------|-------------|----------------|--------|
| ... | ... | never | no | Drop |
| ... | ... | never | yes — verify | Check rule |

<details>
<summary>Relabeling config to drop unused metrics</summary>

​```yaml
# Add to vmagent metric_relabel_configs (VMServiceScrape or global)
metric_relabel_configs:
  - source_labels: [__name__]
    regex: "metric1|metric2|metric3"
    action: drop
​```
</details>

### 2. High-Cardinality Labels
**Potential savings: ~X series (Y%)**

| Label | Unique Values | Top Affected Metrics | Pattern | Action |
|-------|--------------|---------------------|---------|--------|
| user_id | 50,000 | http_requests_total | UUID | Drop |
| path | 10,000 | http_request_duration | URL paths | Aggregate |
| error_message | 5,000 | app_errors_total | Long strings | Drop |

<details>
<summary>Drop labels that should never be in metrics</summary>

​```yaml
metric_relabel_configs:
  - regex: "user_id|request_id|session_id|trace_id|error_message|sql_query"
    action: labeldrop
​```
</details>

<details>
<summary>Stream aggregation for high-cardinality HTTP labels</summary>

​```yaml
# vmagent stream aggregation config
- match: '{__name__=~"http_request.*"}'
  interval: 1m
  without: [path, instance, pod]
  outputs: [total]
  # drop_input: true  # enable after verifying aggregated output

- match: '{__name__=~"http_request_duration.*_bucket"}'
  interval: 1m
  without: [pod, instance]
  outputs: [total]
  keep_metric_names: true
​```
</details>

<details>
<summary>Normalize URL paths via relabeling</summary>

​```yaml
metric_relabel_configs:
  - source_labels: [path]
    regex: "/api/v1/users/[^/]+"
    target_label: path
    replacement: "/api/v1/users/:id"
  - source_labels: [path]
    regex: "/api/v1/orders/[^/]+"
    target_label: path
    replacement: "/api/v1/orders/:id"
​```
</details>

### 3. Histogram Optimization
**Potential savings: ~X series (Y%)**

| Metric | Bucket Count | Recommendation |
|--------|-------------|----------------|
| ... | 30 | Reduce to standard 11 buckets |

### 4. Series Churn
| Observation | Value |
|------------|-------|
| Yesterday / today ratio | X:1 |
| Primary driver | Pod restarts / short-lived jobs |

### Summary
| Category | Est. Series Saved | % of Total | Effort |
|----------|------------------|-----------|--------|
| Drop unused metrics | X | Y% | Low — relabeling only |
| Drop bad labels | X | Y% | Low — labeldrop |
| Stream aggregation | X | Y% | Medium — new config |
| Histogram reduction | X | Y% | Low — bucket filtering |
| **Total** | **X** | **Y%** | |

### Implementation Priority
1. **[Low effort]** Drop unused metrics — pure relabeling, no data loss risk
2. **[Low effort]** Drop labels that should never be in metrics (IDs, messages, SQL)
3. **[Medium effort]** Stream aggregation for high-cardinality HTTP/app metrics
4. **[Medium effort]** Histogram bucket reduction
```

Adapt the template to actual findings — omit sections with no findings, expand sections
with significant findings.

---

## Remediation Reference

### Relabeling (metric_relabel_configs)

Applied at scrape time or remote write. Changes affect new data immediately.

**Drop entire metrics:**

```yaml
metric_relabel_configs:
  - source_labels: [__name__]
    regex: "metric_to_drop|another_metric"
    action: drop
```

**Drop labels:**

```yaml
metric_relabel_configs:
  - regex: "label_to_drop|another_label"
    action: labeldrop
```

**Normalize label values (reduce unique values):**

```yaml
metric_relabel_configs:
  - source_labels: [path]
    regex: "/api/v1/users/[^/]+"
    target_label: path
    replacement: "/api/v1/users/:id"
```

### Stream Aggregation

Applied at vmagent level. Aggregates in-flight before writing to storage.
Docs: <https://docs.victoriametrics.com/victoriametrics/stream-aggregation/>

**Remove labels while preserving metric semantics:**

```yaml
- match: '{__name__=~"http_.*"}'
  interval: 1m
  without: [instance, pod]
  outputs: [total]
```

**Aggregate counters (drop high-cardinality dimension):**

```yaml
- match: 'http_requests_total'
  interval: 30s
  without: [path, user_id]
  outputs: [total]
```

**Aggregate histograms:**

```yaml
- match: '{__name__=~".*_bucket"}'
  interval: 1m
  without: [pod, instance]
  outputs: [quantiles(0.5, 0.9, 0.99)]
  keep_metric_names: true
```

**Common output functions:**

| Function | Use for | Example |
|----------|---------|---------|
| `total` | Counters (running sum) | request counts |
| `sum_samples` | Gauge sums | memory usage across pods |
| `count_samples` | Sample counts | number of reporting instances |
| `last` | Latest gauge value | current temperature |
| `min`, `max` | Extremes | peak latency |
| `avg` | Averages | mean CPU usage |
| `quantiles(0.5, 0.9, 0.99)` | Distribution estimation | latency percentiles |
| `histogram_bucket` | Re-bucket histograms | reduce bucket granularity |

**Important**: use `total` for counters, `last`/`avg`/`sum_samples` for gauges. Using `total` on
gauges produces nonsensical running sums.

### Where to Apply in Kubernetes

| Method | CRD / Config | Scope |
|--------|-------------|-------|
| `metric_relabel_configs` | `VMServiceScrape` / `VMPodScrape` `.spec.metricRelabelConfigs` | Per scrape target |
| Global relabeling | VMAgent `-remoteWrite.relabelConfig` | All metrics |
| Stream aggregation | VMAgent `-remoteWrite.streamAggr.config` | All remote-written metrics |
| Per-remote-write SA | VMAgent `.spec.remoteWrite[].streamAggrConfig` | Per destination |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Dropping a metric used by alerts | Always cross-check `/api/v1/rules` before dropping |
| `drop_input: true` without testing | Verify aggregation output matches expectations first |
| Stream aggregating gauges with `total` | Use `last`, `avg`, or `sum_samples` for gauges |
| Forgetting `keep_metric_names: true` | Without it, output gets long auto-generated suffix |
| Dropping `le` label entirely from histograms | Only drop specific `le` values, never the label itself |
| Not considering recording rule dependencies | Check both alerting AND recording rules |
| Applying relabeling without testing | Use `-dryRun` flag or test on a single scrape target first |
