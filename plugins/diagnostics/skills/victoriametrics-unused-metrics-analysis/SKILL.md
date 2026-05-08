---
name: victoriametrics-unused-metrics-analysis
description: >
  Find unused and rarely-queried metrics in VictoriaMetrics using the metric_names_stats API,
  then suggest optimization actions (drop rules, relabel configs). Use this skill when the user
  wants to find unused metrics, identify wasted storage, optimize metric ingestion, reduce
  cardinality by dropping unneeded metrics, clean up scrape targets, or asks about which metrics
  are never queried. Also trigger when the user mentions "metric cleanup", "unused series",
  "what metrics can I drop", "metric optimization", "wasted ingestion", or wants to reduce
  VictoriaMetrics resource consumption by eliminating unnecessary metrics.
allowed-tools: Bash(curl:*), Bash(jq:*)
---

# Find Unused Metrics in VictoriaMetrics

Identify metrics that are being ingested but never (or rarely) queried, then recommend concrete actions to stop wasting storage and ingestion resources.

## Environment

Uses the same env vars as the `victoriametrics-query` skill:

```bash
# $VM_METRICS_URL - base URL
#   cluster: export VM_METRICS_URL="https://vmselect.example.com/select/0/prometheus"
#   single: export VM_METRICS_URL="http://localhost:8428"
# $VM_AUTH_HEADER - auth header (empty if no auth is required)
```

## How It Works

VictoriaMetrics tracks how many times each metric name is fetched during queries, and when it was last fetched. This is done via the `metric_names_stats` API, available since v1.113.0. By comparing what's ingested against what's actually queried, you can find metrics that nobody uses and safely drop them.

The workflow has three phases:

```
Phase 1: Verify feature is enabled
Phase 2: Collect and analyze usage data
Phase 3: Report findings and suggest fixes
```

## Phase 1: Verify Feature Availability

Before doing anything, check that the metric names stats tracker is returning data. The feature is enabled by default since v1.113.0, but may have been disabled or the instance may be too old.

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/metric_names_stats?limit=3" | jq .
```

**If the response has an empty `records` array or returns an error**, the feature is not active. Guide the user:

> The metric names stats tracker is not returning data. This can happen if:
>
> 1. **VictoriaMetrics version is older than v1.113.0** — upgrade to v1.113.0+
> 2. **Stats were recently reset** — the tracker needs time to accumulate query data after a restart or reset
>
> For cluster mode, this flag must be set on **vmstorage** nodes.
> See: <https://docs.victoriametrics.com/victoriametrics/single-server-victoriametrics/#track-ingested-metrics-usage>

Stop here if the feature is not available. The rest of the workflow depends on it.

**If records exist**, note the `statsCollectedSince` timestamp — this tells you how long the tracker has been accumulating data. Longer collection periods give more reliable results. Mention the collection window to the user so they can judge confidence:

- **< 1 day**: Too early to draw conclusions — many metrics are queried periodically (daily dashboards, weekly reports, monthly alerts)
- **1-7 days**: Useful for finding obviously unused metrics, but may miss weekly patterns
- **> 7 days**: Good confidence for identifying truly unused metrics
- **> 30 days**: High confidence — if a metric hasn't been queried in 30+ days, it's very likely unused

## Phase 2: Collect and Analyze

### Step 1: Get all never-queried metric names

These are metrics with `queryRequests: 0` — tracked but never fetched by any query, dashboard, alert rule, or recording rule.

Use a high limit to capture all of them — the default 1000 is often not enough:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/metric_names_stats?le=0&limit=50000" | jq .
```

The `le=0` parameter filters to metrics queried zero times. Save the full list of metric names from the response.

### Step 2: Separate active waste from historical noise

This is the critical step. The `metric_names_stats` tracker records ALL metric names it has ever seen, including ones from decommissioned sources that no longer have active time series. Metrics with 0 active series will expire naturally with retention — they are not wasting ingestion resources and need no action.

The goal is to find metrics that ARE being actively ingested but NOT being queried.

**Important**: A prefix group like `container_*` or `node_*` typically contains a mix of queried and never-queried metric names. For example, `container_cpu_usage_seconds_total` may be heavily queried while `container_blkio_device_usage_total` is never queried — but both share the `container_` prefix. You must count series only for the specific never-queried metric names, not the entire prefix.

**Approach**: Group the never-queried metric names from Step 1 by prefix, then build a regex of only the never-queried names within each group to count their series:

```bash
# WRONG — counts ALL container metrics including queried ones:
# count({__name__=~"container_.+"})

# CORRECT — counts only the specific never-queried metric names:
# Build a regex from the actual never-queried names in that prefix group
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'query=count({__name__=~"container_blkio_device_usage_total|container_file_descriptors|container_last_seen|container_memory_failcnt|container_sockets|container_tasks_state"})' \
  "$VM_METRICS_URL/api/v1/query" | jq '.data.result[0].value[1]'
```

For prefix groups where ALL metric names in the group are never-queried (e.g., all `go_godebug_*` metrics), you can use the prefix regex since there's nothing queried to accidentally include.

Work through the major prefix groups from the Step 1 results. For each group:

1. Check if the prefix contains a mix of queried and never-queried metrics, or if all metrics under the prefix are never-queried
2. For mixed prefixes: build a regex from the specific never-queried names
3. For fully-unqueried prefixes: use the prefix regex directly
4. If `count()` returns `null` or `0` → these are historical-only metrics, note them but deprioritize
5. If `count()` returns a positive number → these are actively ingested waste, prioritize for the report

Do NOT spend time individually querying hundreds of historical metrics with 0 series. Focus your effort on the groups that have active series — those are the ones worth reporting.

### Step 3: Get rarely-queried metrics

These are metrics queried only a handful of times — possibly from one-off exploration rather than active use.

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/metric_names_stats?le=5&limit=50000" | jq .
```

Subtract the never-queried set to isolate the "queried 1-5 times" group.

### Step 4: Get total tracked metric count and total active series

This gives context for what percentage of metrics are unused and how much impact dropping them would have.

```bash
# Total tracked metric names
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/metric_names_stats?limit=1" | jq '.statsCollectedRecordsTotal'

# Total active time series
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'query=count({__name__=~".+"})' \
  "$VM_METRICS_URL/api/v1/query" | jq '.data.result[0].value[1]'
```

### Step 5: Estimate series count per active unused metric group

You should already have these numbers from Step 2. If any prefix groups are missing counts, query them now — remembering to count only the specific never-queried metric names within each group (see the WRONG vs CORRECT pattern in Step 2).

### Step 6: Categorize unused metrics

Group the active unused metrics into categories to make the report actionable. Common categories:

- **Kubernetes infrastructure metrics** (e.g., `kube_*`, `container_*`, `node_*` prefixes that aren't used in any dashboard or alert)
- **Application metrics** (custom app metrics nobody built dashboards for)
- **Exporter bloat** (exporters often emit hundreds of metrics, most unused — e.g., `go_*`, `process_*`, `promhttp_*`)
- **Deprecated metrics** (old metric names replaced by newer versions)

Separately note the **historical-only metrics** (0 active series) in a brief section — these need no action but show the user what will naturally expire.

## Phase 3: Report and Recommend

### Report Structure

Present findings in this format:

```
## Unused Metrics Report

**Collection window**: [statsCollectedSince date] to now ([N] days)
**Total tracked metric names**: [statsCollectedRecordsTotal]
**Total active time series**: [count]
**Never queried (with active series)**: [count] metrics, ~[M] series ([percentage]% of active series)
**Never queried (historical only, 0 series)**: [count] metrics — will expire with retention, no action needed
**Rarely queried (1-5 times)**: [count] metrics ([percentage]%)
**Queried long time ago (30+ days)**: [count] metrics ([percentage]%)

### Never-Queried Active Metrics by Category

#### [Category Name] — [N] metrics, ~[M] active series
| Metric Pattern | Series Count | Recommendation |
|---|---|---|
| `prefix_*` | ~X,000 | Drop via relabel |

### Rarely-Queried Metrics
[Similar table, but note last query time from lastRequestTimestamp]

### Historical-Only Metrics (No Action Needed)
[Brief list of prefix groups with 0 active series — these are from decommissioned sources and will expire with retention]

### Estimated Impact
- Dropping all never-queried active metrics would eliminate ~[N] series ([X]% of total active)
- Top 3 categories alone account for ~[M] series
```

### Recommended Actions

For each category of unused metrics, suggest one of these actions:

**1. Drop at vmagent via `metric_relabel_configs`** (preferred for metrics you're confident are unused):

```yaml
# Add to vmagent scrape config or VMServiceScrape/VMPodScrape
metric_relabel_configs:
  - source_labels: [__name__]
    regex: "metric_prefix_.+"
    action: drop
```

**2. Drop at vmagent via global `-relabelConfig`** (for broad patterns across all scrape targets):

```yaml
# vmagent -relabelConfig=relabel.yaml
- source_labels: [__name__]
  regex: "go_memstats_.+|process_virtual_memory_.+|promhttp_.+"
  action: drop
```

**3. Keep but investigate** (for rarely-queried metrics — someone might still need them):
> These metrics were queried a few times in the collection window. Before dropping, verify they aren't used in:
>
> - Grafana dashboards (search dashboard JSON for the metric name)
> - Alert rules (check VMRule / PrometheusRule CRDs)
> - Recording rules
> - External systems querying the API

### Safety Notes

Always communicate these caveats:

- **Start with a test period**: Before permanently dropping metrics, use `drop` rules on a staging vmagent to verify nothing breaks.
- **Check alert rules and recording rules**: Metrics queried only by recording rules or alerts may show low `queryRequests` counts but are still essential. Cross-reference with `api/v1/rules` output.
- **Dashboard queries aren't tracked until viewed**: A metric used in a Grafana dashboard that nobody opened during the collection window will appear as "unused." Consider querying Grafana's API for dashboard definitions to cross-reference.
- **Some metrics are queried seasonally**: Monthly or quarterly reports will show low query counts. The longer the collection window, the more reliable the results.
- **Never drop `up` or meta-metrics**: Metrics like `up`, `scrape_duration_seconds`, `scrape_samples_scraped` are essential for monitoring health even if rarely queried directly.
