# VictoriaMetrics HTTP API Reference

Base URL: `$VM_METRICS_URL`

- cluster vmselect: `https://vmselect.example.com/select/0/prometheus`
- single-node: `http://localhost:8428`

## Query Endpoints

### GET/POST /api/v1/query — Instant Query

Evaluate a MetricsQL/PromQL expression at a single point in time.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | MetricsQL expression |
| `time` | No | RFC3339 or Unix seconds | now | Evaluation timestamp |
| `step` | No | duration string | - | Step for range vector selectors |
| `timeout` | No | duration string | - | Query timeout |

Response:

```json
{
  "status": "success",
  "data": {
    "resultType": "vector",
    "result": [
      {
        "metric": {"__name__": "up", "job": "kubelet", "namespace": "kube-system"},
        "value": [1709769600, "1"]
      }
    ]
  }
}
```

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/query?query=up&time=2026-03-07T09:00:00Z" | jq .
```

### GET/POST /api/v1/query_range — Range Query

Evaluate a MetricsQL expression over a time range.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | MetricsQL expression |
| `start` | Yes | RFC3339 or Unix seconds | - | Start timestamp |
| `end` | No | RFC3339 or Unix seconds | now | End timestamp |
| `step` | Yes | duration string or seconds | - | Query resolution step (e.g., `5m`, `300`) |
| `timeout` | No | duration string | - | Query timeout |

Response:

```json
{
  "status": "success",
  "data": {
    "resultType": "matrix",
    "result": [
      {
        "metric": {"__name__": "up", "job": "kubelet"},
        "values": [[1709769600, "1"], [1709769900, "1"]]
      }
    ]
  }
}
```

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'query=rate(http_requests_total[5m])' \
  "$VM_METRICS_URL/api/v1/query_range?start=2026-03-07T00:00:00Z&end=2026-03-07T12:00:00Z&step=5m" | jq .
```

## Discovery Endpoints

### GET/POST /api/v1/labels — Label Names

List all label names.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `match[]` | No | string (series selector) | Filter to specific series |
| `start` | No | RFC3339 or Unix seconds | Start of time range |
| `end` | No | RFC3339 or Unix seconds | End of time range |

Response:

```json
{
  "status": "success",
  "data": ["__name__", "container", "instance", "job", "namespace", "pod"]
}
```

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/labels" | jq '.data[]'
```

### GET/POST /api/v1/label/{label_name}/values — Label Values

Get values for a specific label. `label_name` is a PATH segment, not a query parameter.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `match[]` | No | string (series selector) | Filter to matching series |
| `start` | No | RFC3339 or Unix seconds | Start of time range |
| `end` | No | RFC3339 or Unix seconds | End of time range |

Response:

```json
{
  "status": "success",
  "data": ["default", "kube-system", "monitoring", "myapp"]
}
```

Examples:

```bash
# All values for "namespace" label
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/label/namespace/values" | jq '.data[]'

# Values filtered by series
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'match[]={job="kubelet"}' \
  "$VM_METRICS_URL/api/v1/label/namespace/values" | jq '.data[]'
```

### GET/POST /api/v1/series — Series Discovery

Find time series matching label selectors.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `match[]` | Yes | string (series selector) | Series selectors (can be repeated) |
| `start` | No | RFC3339 or Unix seconds | Start of time range |
| `end` | No | RFC3339 or Unix seconds | End of time range |
| `limit` | No | integer | Max series to return |

Response:

```json
{
  "status": "success",
  "data": [
    {"__name__": "up", "job": "kubelet", "namespace": "kube-system", "instance": "10.0.0.1:10250"}
  ]
}
```

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'match[]={namespace="myapp"}' \
  "$VM_METRICS_URL/api/v1/series?limit=20" | jq '.data[]'
```

### GET /api/v1/metadata — Metric Metadata

Get type and help text for metrics.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `metric` | No | string | Metric name search keyword |
| `limit` | No | integer | Max results |

Note: The raw API uses `metric` parameter.

Response:

```json
{
  "status": "success",
  "data": {
    "http_requests_total": [
      {"type": "counter", "help": "Total number of HTTP requests", "unit": ""}
    ]
  }
}
```

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/metadata?metric=http_request&limit=10" | jq .
```

## Alerts and Rules

### GET /api/v1/alerts — Active Alerts

Returns all firing and pending alerts. No parameters.

Response:

```json
{
  "status": "success",
  "data": {
    "alerts": [
      {
        "labels": {"alertname": "HighMemory", "namespace": "myapp"},
        "annotations": {"summary": "Memory usage is high"},
        "state": "firing",
        "activeAt": "2026-03-07T08:00:00Z",
        "value": "0.95"
      }
    ]
  }
}
```

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/alerts" | jq '.data.alerts[]'
```

### GET /api/v1/rules — Alerting and Recording Rules

Returns all configured rules. No parameters.

Response:

```json
{
  "status": "success",
  "data": {
    "groups": [
      {
        "name": "kubernetes-apps",
        "rules": [
          {
            "name": "KubePodCrashLooping",
            "query": "max_over_time(...)",
            "type": "alerting",
            "state": "inactive"
          }
        ]
      }
    ]
  }
}
```

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/rules" | jq '.data.groups[] | {name, rules: [.rules[] | select(.state != "inactive") | .name]}'
```

## Status/Diagnostic Endpoints

### GET /api/v1/status/tsdb — TSDB Status

Cardinality statistics. No parameters.

Key fields in response:

- `seriesCountByMetricName` — top metrics by series count
- `seriesCountByLabelName` — top labels by series count
- `seriesCountByLabelValuePair` — top label=value pairs
- `labelValueCountByLabelName` — labels with most unique values
- `totalSeries` — total active time series

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/tsdb" | jq '{total: .data.totalSeries, top_metrics: .data.seriesCountByMetricName[:5]}'
```

### GET /api/v1/status/active_queries — Active Queries

Currently executing queries. No parameters.

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/active_queries" | jq .
```

### GET /api/v1/status/top_queries — Top Queries

Most frequent and slowest queries.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `topN` | No | integer | Number of top queries to return |
| `maxLifetime` | No | duration string | Time window to consider |

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/top_queries?topN=10" | jq '.data.topByCount[:5]'
```

### GET /api/v1/status/buildinfo — Build Info

Version information. No parameters.

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/buildinfo" | jq .
```

## Export Endpoints

### POST /api/v1/export — Export Raw Data

Export raw time series samples in JSON lines format.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `match[]` | Yes | string (series selector) | Series to export (can be repeated) |
| `start` | No | RFC3339 or Unix seconds | Start of time range |
| `end` | No | RFC3339 or Unix seconds | End of time range |
| `reduce_mem_usage` | No | integer (1) | Reduce memory usage for large exports |

Response: JSON lines (one JSON object per line, NOT wrapped in standard API response):

```json
{"metric":{"__name__":"http_requests_total","job":"api","namespace":"myapp"},"values":[1,2,3],"timestamps":[1709769600000,1709769900000,1709770200000]}
{"metric":{"__name__":"http_requests_total","job":"api","namespace":"other"},"values":[4,5,6],"timestamps":[1709769600000,1709769900000,1709770200000]}
```

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'match[]=http_requests_total' \
  -d 'start=2026-03-07T00:00:00Z' -d 'end=2026-03-07T12:00:00Z' \
  -d 'reduce_mem_usage=1' \
  "$VM_METRICS_URL/api/v1/export" | head -5
```

Also available:

- `POST /api/v1/export/csv` — CSV format. Additional params: `format` (column spec, e.g., `__name__,__value__,__timestamp__:unix_s`)
- `POST /api/v1/export/native` — Native binary format (for import via `POST /api/v1/import/native`)

### GET /api/v1/series/count — Series Count

Total number of active time series. No parameters.

Response:

```json
{
  "status": "success",
  "data": 123456789
}
```

Note: Can be slow on large databases. May return slightly inflated values due to internal implementation.

### GET /api/v1/status/metric_names_stats — Metric Usage Statistics

Statistics on which metrics are being queried and how frequently.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `limit` | No | integer | Max results to return (default 1000) |
| `le` | No | integer | Max query count threshold — returns metrics queried at most N times |
| `match_pattern` | No | string | Metric name prefix filter |

Example:

```bash
# Metrics queried 0 or 1 times (candidates for removal)
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/metric_names_stats?limit=50&le=1" | jq .

# Metrics matching prefix
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "$VM_METRICS_URL/api/v1/status/metric_names_stats?match_pattern=vm_&limit=20" | jq .
```

### GET /flags — Non-Default Flags

Root-level endpoint. Returns runtime flags that differ from defaults.

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  "${VM_METRICS_URL%%/select/*}/flags" | jq .
```

## Query Tool Endpoints

These are ROOT-level endpoints, NOT under `/api/v1/`. On cluster mode the base path differs from the metrics API path.

### GET /expand-with-exprs — Expand WITH Expressions

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `query` | Yes | string | MetricsQL expression with WITH clauses |

Returns: plain text (expanded expression), not JSON.

### GET /prettify-query — Prettify Query

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `query` | Yes | string | MetricsQL expression |

Returns: JSON with prettified query string.

Note: Both endpoints return 404 on some VM versions. Verified working depends on version.

## Config Debug Endpoints

Root-level endpoints for debugging VictoriaMetrics configuration. Accept POST with form data. Return HTML by default (designed for VMUI), but useful via curl for quick validation.

### POST /metric-relabel-debug — Debug Relabeling Rules

Test how metric relabeling rules transform a metric.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `metric` | Yes | string | Metric in Prometheus exposition format (e.g., `foo{bar="baz"}`) |
| `relabel_config` | Yes | string | YAML relabeling config (same format as `-relabelConfig` file) |

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  -d 'metric=foo{bar="baz"}' \
  -d 'relabel_config=- target_label: cluster
  replacement: dev' \
  "${VM_METRICS_URL%%/select/*}/metric-relabel-debug"
```

### POST /downsampling-filters-debug — Debug Downsampling Rules

Test which downsampling rules match a given metric.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `metric` | Yes | string | Metric in Prometheus exposition format |
| `downsampling_period` | Yes | string | Downsampling config (same format as `-downsampling.period` flag) |

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  -d 'metric=foo{bar="baz"}' \
  -d 'downsampling_period=30d:5m,180d:1h' \
  "${VM_METRICS_URL%%/select/*}/downsampling-filters-debug"
```

### POST /retention-filters-debug — Debug Retention Filters

Test which retention policy applies to a given metric.

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `metric` | Yes | string | Metric in Prometheus exposition format |
| `retention_period` | Yes | string | Retention config (same format as `-retentionPeriod` flag) |

Example:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  -d 'metric=foo{bar="baz"}' \
  -d 'retention_period=2y,{env="dev"}:30d' \
  "${VM_METRICS_URL%%/select/*}/retention-filters-debug"
```

Note: All three debug endpoints return HTML. For interactive use, access VMUI at `${VM_METRICS_URL%%/select/*}/vmui/#/relabeling`, `vmui/#/downsampling`, or `vmui/#/retention`.

## HTTP Method and Content-Type Summary

| Endpoint | GET | POST | POST Content-Type |
|----------|-----|------|-------------------|
| `/api/v1/query` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/api/v1/query_range` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/api/v1/labels` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/api/v1/label/{name}/values` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/api/v1/series` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/api/v1/metadata` | Yes | No | N/A |
| `/api/v1/alerts` | Yes | No | N/A |
| `/api/v1/rules` | Yes | No | N/A |
| `/api/v1/status/*` | Yes | No | N/A |
| `/api/v1/export` | No | Yes | `application/x-www-form-urlencoded` |
| `/api/v1/series/count` | Yes | No | N/A |
| `/api/v1/status/metric_names_stats` | Yes | No | N/A |
| `/flags` | Yes | No | N/A |
| `/expand-with-exprs` | Yes | No | N/A |
| `/prettify-query` | Yes | No | N/A |
| `/metric-relabel-debug` | No | Yes | `application/x-www-form-urlencoded` |
| `/downsampling-filters-debug` | No | Yes | `application/x-www-form-urlencoded` |
| `/retention-filters-debug` | No | Yes | `application/x-www-form-urlencoded` |

For POST requests, use `--data-urlencode` with curl to properly encode query parameters containing special characters:

```bash
curl -s ${VM_AUTH_HEADER:+-H} ${VM_AUTH_HEADER:+"$VM_AUTH_HEADER"} \
  --data-urlencode 'query=sum(rate(http_requests_total{code=~"5.."}[5m])) by (namespace)' \
  "$VM_METRICS_URL/api/v1/query"
```

## Timestamp Format

All timestamp parameters accept:

- RFC3339: `2026-03-07T09:00:00Z`
- Unix seconds: `1709769600`
- Relative (VictoriaMetrics extension): `now-1h`, `now-30m` (not standard PromQL)

Step parameters accept duration strings: `5m`, `1h`, `30s`, `300` (seconds as integer).
