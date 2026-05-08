---
name: victoriametrics-query
description: >
  Query VictoriaMetrics metrics via curl. Use when running PromQL/MetricsQL queries, discovering metrics/labels,
  checking alerts and rules, inspecting TSDB status, exporting raw data, checking metric usage statistics,
  or debugging relabeling/downsampling/retention configs. Triggers on: metric queries, PromQL, MetricsQL,
  label discovery, series exploration, cardinality checks, alert status, recording rules, active/top queries,
  export data, metric statistics, relabel debug, downsampling debug, retention debug, flags.
allowed-tools: Bash(curl:*)
---

# VictoriaMetrics Metrics Query

Query VictoriaMetrics HTTP API directly via curl. Covers instant/range queries, label/series discovery, alerts, rules, instance diagnostics, raw data export, metric usage statistics, and config debugging tools.

## Environment

```bash
# $VM_METRICS_URL - base URL
#   cluster: export VM_METRICS_URL="https://vmselect.example.com/select/0/prometheus"
#   single: export VM_METRICS_URL="http://localhost:8428"
# $VM_AUTH_HEADER - auth header (set for prod, empty for local)
```

## Auth Pattern

All curl commands use conditional auth — works for both prod and local:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} "$VM_METRICS_URL/api/v1/query?query=up" | jq .
```

When `VM_AUTH_HEADER` is empty, `-H` flag is omitted automatically.

## Core Endpoints

### Instant Query

```bash
# Query at current time
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/query?query=up" | jq .

# Query at specific time
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/query?query=up&time=2026-03-07T09:00:00Z" | jq .
```

Parameters: `query` (required), `time` (optional, RFC3339 or Unix seconds), `step`, `timeout`

### Range Query

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/query_range?query=rate(http_requests_total[5m])&start=2026-03-07T00:00:00Z&end=2026-03-07T12:00:00Z&step=5m" | jq .
```

Parameters: `query` (required), `start` (required), `end` (optional), `step` (required). Times in RFC3339 or Unix seconds.

### Labels Discovery

```bash
# All label names
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/labels" | jq '.data[]'

# Label values (label_name is a PATH parameter)
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/label/namespace/values" | jq '.data[]'

# Label values filtered by series matcher
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'match[]={job="kubelet"}' \
  "$VM_METRICS_URL/api/v1/label/namespace/values" | jq '.data[]'
```

### Series Discovery

```bash
# Find series matching selector
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'match[]={namespace="myapp"}' \
  "$VM_METRICS_URL/api/v1/series?limit=20" | jq '.data[].__name__'
```

Parameters: `match[]` (required), `start`, `end`, `limit`

### Metric Metadata

```bash
# Search by metric name keyword
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/metadata?metric=http_request&limit=10" | jq .
```

Parameters: `metric` (search keyword), `limit`.

### Alerts and Rules

```bash
# All firing/pending alerts
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/alerts" | jq '.data.alerts[]'

# All alerting and recording rules
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/rules" | jq '.data.groups[]'
```

### Instance Diagnostics

```bash
# TSDB cardinality stats
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/tsdb" | jq .

# Currently executing queries
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/active_queries" | jq .

# Most frequent/slowest queries
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/top_queries?topN=10" | jq .

# Version info
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/buildinfo" | jq .
```

### Export Raw Data

```bash
# Export raw samples as JSON lines (one JSON object per line)
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'match[]=http_requests_total' \
  -d 'start=2026-03-07T00:00:00Z' -d 'end=2026-03-07T12:00:00Z' \
  "$VM_METRICS_URL/api/v1/export" | head -5

# Export with reduced memory usage (for large exports)
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'match[]={namespace="myapp"}' \
  -d 'start=2026-03-07T00:00:00Z' -d 'end=2026-03-07T01:00:00Z' \
  -d 'reduce_mem_usage=1' \
  "$VM_METRICS_URL/api/v1/export" > export.jsonl
```

Parameters: `match[]` (required), `start`, `end`, `reduce_mem_usage`. Output is JSON lines (not wrapped in a standard API response).

Each line: `{"metric":{"__name__":"...","label":"value"},"values":[...],"timestamps":[...]}`

Also available: `/api/v1/export/csv` (CSV format), `/api/v1/export/native` (binary, for import via `/api/v1/import/native`).

### Series Count

```bash
# Total number of active time series
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/series/count" | jq .
```

Note: can be slow on large databases and may return slightly inflated values.

### Metric Usage Statistics

```bash
# Which metrics are being queried, and how often
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/metric_names_stats?limit=20" | jq .

# Metrics queried <= N times (find unused/rarely-used metrics)
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/metric_names_stats?limit=50&le=1" | jq .

# Filter by metric name pattern
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/metric_names_stats?match_pattern=vm_&limit=20" | jq .
```

Parameters: `limit` (max results), `le` (max query count threshold — find metrics queried at most N times), `match_pattern` (metric name prefix filter).

### Flags (Non-Default)

```bash
# View non-default runtime flags (returns plain text, one flag per line — NOT JSON)
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "${VM_METRICS_URL%%/select/*}/flags"
```

Root-level endpoint. Returns plain text (not JSON), one flag per line. Shows only flags that differ from defaults — useful for debugging configuration.

### Query Tools

These are ROOT-level endpoints, NOT under `/api/v1/`. On cluster mode, strip the `/select/0/prometheus` prefix to get the base host.

```bash
# Expand WITH expressions (returns text, not JSON)
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "${VM_METRICS_URL%%/select/*}/expand-with-exprs?query=WITH(x=up)x"

# Prettify MetricsQL query (returns JSON)
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "${VM_METRICS_URL%%/select/*}/prettify-query?query=rate(x[5m])" | jq .
```

Note: `${VM_METRICS_URL%%/select/*}` strips everything from `/select` onward, yielding the base host. On single-node (local), `VM_METRICS_URL` has no `/select` prefix so it returns the URL unchanged.

### Config Debug Tools

Root-level endpoints for debugging relabeling, downsampling, and retention configurations. These accept POST with form data. Primarily used via VMUI but accessible via curl.

```bash
# Debug metric relabeling rules — test how a metric is transformed
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  -d 'metric=foo{bar="baz"}' \
  -d 'relabel_config=- target_label: cluster
  replacement: dev' \
  "${VM_METRICS_URL%%/select/*}/metric-relabel-debug"

# Debug downsampling filters — test which downsampling rules match a metric
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  -d 'metric=foo{bar="baz"}' \
  -d 'downsampling_period=30d:5m,180d:1h' \
  "${VM_METRICS_URL%%/select/*}/downsampling-filters-debug"

# Debug retention filters — test which retention policy applies to a metric
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  -d 'metric=foo{bar="baz"}' \
  -d 'retention_period=2y,{env="dev"}:30d' \
  "${VM_METRICS_URL%%/select/*}/retention-filters-debug"
```

These return HTML by default. For programmatic use, the VMUI at `${VM_METRICS_URL%%/select/*}/vmui/#/relabeling` provides an interactive interface.

## Timestamp Format

All times accept RFC3339 (`2026-03-07T09:00:00Z`) or Unix seconds (`1709769600`). Default `time` for instant queries is "now". Default `end` for range queries is "now".

## Response Parsing (jq)

```bash
# Extract metric values from instant query
... | jq '.data.result[] | {metric: .metric.__name__, value: .value[1]}'

# Extract time series from range query
... | jq '.data.result[] | {metric: .metric, values: [.values[] | {time: .[0], value: .[1]}]}'

# List metric names from series response
... | jq '[.data[] | .__name__] | unique'

# Count alerts by state
... | jq '.data.alerts | group_by(.state) | map({state: .[0].state, count: length})'

# Top series by cardinality from tsdb status
... | jq '.data.seriesCountByMetricName[:10]'
```

## Common Patterns

```bash
# Check if a metric exists
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/query?query=count({__name__=~\"http_request.*\"})" | jq '.data.result[].value[1]'

# Get all namespaces with active pods
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'match[]={__name__="kube_pod_info"}' \
  "$VM_METRICS_URL/api/v1/label/namespace/values" | jq '.data[]'

# Rate of errors over last hour
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'query=sum(rate(http_requests_total{code=~"5.."}[5m])) by (namespace)' \
  "$VM_METRICS_URL/api/v1/query" | jq '.data.result[] | {ns: .metric.namespace, rate: .value[1]}'
```

## Environment Switching

```bash
# Check current environment
echo "VM_METRICS_URL: $VM_METRICS_URL"
echo "VM_AUTH_HEADER: $( [ -n "$VM_AUTH_HEADER" ] && echo '(set)' || echo '(empty)' )"
```

## Important Notes

- POST endpoints accept `application/x-www-form-urlencoded` (use `--data-urlencode` for query params with special chars)
- `match[]` parameter requires the `[]` suffix — `match` alone won't work
- For metric metadata, raw API uses `metric` param
- `label_values` uses a path parameter: `/api/v1/label/{label_name}/values`
- `expand-with-exprs`, `prettify-query`, `flags`, `metric-relabel-debug`, `downsampling-filters-debug`, and `retention-filters-debug` are root-level paths, not under `/api/v1/`
- Export endpoint (`/api/v1/export`) returns JSON lines (one object per line), not standard API response JSON
- Debug endpoints (`metric-relabel-debug`, etc.) return HTML by default — best used via VMUI for interactive debugging
- For full endpoint details, parameters, and response formats, see `references/api-reference.md`
