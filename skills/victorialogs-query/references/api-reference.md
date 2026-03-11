# VictoriaLogs HTTP API Reference

Full endpoint documentation for VictoriaLogs log queries. Verified against official VictoriaLogs docs and live local endpoint (2026-03-07).

Base URL: `$VM_LOGS_URL`
- Prod: `https://vlselect.example.com`
- Local: `http://localhost:9428`

## Query Endpoints

### GET/POST /select/logsql/query — Log Query

Search logs using LogsQL. Returns JSON Lines (one JSON object per line), NOT a JSON array.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | LogsQL query expression |
| `start` | Yes | RFC3339 | - | Start of time range. ALWAYS required. |
| `end` | No | RFC3339 | latest available | End of time range |
| `limit` | No | integer | unlimited | Max log entries to return |
| `offset` | No | integer | 0 | Number of entries to skip |
| `fields` | No | string | all | Comma-separated list of fields to return |
| `timeout` | No | duration | - | Query timeout |

Response (JSON Lines — one object per line):
```
{"_time":"2026-03-07T09:00:00Z","_msg":"Connection refused","level":"error","namespace":"myapp","pod":"myapp-abc123"}
{"_time":"2026-03-07T09:00:01Z","_msg":"Retrying connection","level":"warn","namespace":"myapp","pod":"myapp-abc123"}
```

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"} error' \
  "$VM_LOGS_URL/select/logsql/query?start=2026-03-07T00:00:00Z&limit=100"

# Collect JSON Lines into array for jq processing
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"} error' \
  "$VM_LOGS_URL/select/logsql/query?start=2026-03-07T00:00:00Z&limit=100" | jq -s .
```

### GET/POST /select/logsql/stats_query — Instant Stats

Evaluate a LogsQL stats query at a single point in time. Query MUST contain a `| stats` pipe.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | LogsQL query with `| stats` pipe |
| `time` | Yes* | RFC3339 | - | Evaluation timestamp. *Required despite docs marking optional. |
| `start` | No | RFC3339 | - | Alternative to `time` — start of aggregation window |

Response (Prometheus-compatible JSON):
```json
{
  "status": "success",
  "data": {
    "resultType": "vector",
    "result": [
      {
        "metric": {"level": "error"},
        "value": [1709769600, "42"]
      },
      {
        "metric": {"level": "warn"},
        "value": [1709769600, "156"]
      }
    ]
  }
}
```

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"} | stats by (level) count() as total' \
  "$VM_LOGS_URL/select/logsql/stats_query?time=2026-03-07T09:00:00Z" | jq .
```

### GET/POST /select/logsql/stats_query_range — Range Stats

Evaluate a LogsQL stats query over a time range. Query MUST contain a `| stats` pipe.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | LogsQL query with `| stats` pipe |
| `start` | Yes | RFC3339 | - | Start of time range |
| `end` | No | RFC3339 | now | End of time range |
| `step` | No | duration string | - | Resolution step (e.g., `1h`, `5m`) |

Response (Prometheus matrix format):
```json
{
  "status": "success",
  "data": {
    "resultType": "matrix",
    "result": [
      {
        "metric": {"level": "error"},
        "values": [[1709769600, "5"], [1709773200, "12"], [1709776800, "3"]]
      }
    ]
  }
}
```

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"} error | stats count() as total' \
  "$VM_LOGS_URL/select/logsql/stats_query_range?start=2026-03-07T00:00:00Z&end=2026-03-07T12:00:00Z&step=1h" | jq .
```

### GET/POST /select/logsql/hits — Log Hit Counts

Count log entries over time. Useful for log volume analysis.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | LogsQL query |
| `start` | Yes | RFC3339 | - | Start of time range |
| `end` | No | RFC3339 | now | End of time range |
| `step` | Yes | duration string | - | Time bucket size (e.g., `1h`, `5m`). Required. |
| `field` | No | string | - | Group hits by this field |

Response:
```json
{
  "hits": [
    {"timestamps": ["2026-03-07T00:00:00Z", "2026-03-07T01:00:00Z"], "values": [42, 56], "fields": {}}
  ]
}
```

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"}' \
  "$VM_LOGS_URL/select/logsql/hits?start=2026-03-07T00:00:00Z&end=2026-03-07T12:00:00Z&step=1h" | jq .
```

## Discovery Endpoints

### GET/POST /select/logsql/facets — Field Facets

Returns the most frequent values for ALL fields in matching logs. Best single-call discovery tool.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | LogsQL query |
| `start` | Yes | RFC3339 | - | Start of time range |
| `end` | No | RFC3339 | now | End of time range |

Response:
```json
[
  {
    "name": "level",
    "values": [
      {"value": "info", "hits": 5000},
      {"value": "error", "hits": 200},
      {"value": "warn", "hits": 150}
    ]
  },
  {
    "name": "namespace",
    "values": [
      {"value": "myapp", "hits": 3000},
      {"value": "kube-system", "hits": 2000}
    ]
  }
]
```

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"}' \
  "$VM_LOGS_URL/select/logsql/facets?start=2026-03-07T00:00:00Z&end=2026-03-07T12:00:00Z" | jq .
```

### GET/POST /select/logsql/field_names — Non-Stream Field Names

Discover field names present in matching log entries (excludes stream fields).

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | LogsQL query |
| `start` | Yes | RFC3339 | - | Start of time range |
| `end` | No | RFC3339 | now | End of time range |

Response:
```json
[
  {"name": "_msg", "hits": 10000},
  {"name": "level", "hits": 10000},
  {"name": "caller", "hits": 8000},
  {"name": "trace_id", "hits": 3000}
]
```

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"}' \
  "$VM_LOGS_URL/select/logsql/field_names?start=2026-03-07T00:00:00Z" | jq '.[] | .name'
```

### GET/POST /select/logsql/field_values — Field Values

Get values for a specific non-stream field.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | LogsQL query |
| `start` | Yes | RFC3339 | - | Start of time range |
| `field` | Yes | string | - | Field name to get values for |
| `end` | No | RFC3339 | now | End of time range |
| `limit` | No | integer | - | Max values to return |

Response:
```json
[
  {"value": "error", "hits": 500},
  {"value": "warn", "hits": 200},
  {"value": "info", "hits": 10000}
]
```

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"}' \
  "$VM_LOGS_URL/select/logsql/field_values?start=2026-03-07T00:00:00Z&field=level&limit=20" | jq .
```

### GET/POST /select/logsql/stream_field_names — Stream Field Names

Discover stream field names (e.g., namespace, pod, container).

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | LogsQL query |
| `start` | Yes | RFC3339 | - | Start of time range |
| `end` | No | RFC3339 | now | End of time range |

Response:
```json
[
  {"name": "namespace", "hits": 50000},
  {"name": "pod", "hits": 50000},
  {"name": "container", "hits": 50000}
]
```

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query=*' \
  "$VM_LOGS_URL/select/logsql/stream_field_names?start=2026-03-07T00:00:00Z" | jq '.[] | .name'
```

### GET/POST /select/logsql/stream_field_values — Stream Field Values

Get values for a specific stream field.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | LogsQL query |
| `start` | Yes | RFC3339 | - | Start of time range |
| `field` | Yes | string | - | Stream field name |
| `end` | No | RFC3339 | now | End of time range |

Response:
```json
[
  {"value": "myapp", "hits": 30000},
  {"value": "kube-system", "hits": 15000},
  {"value": "monitoring", "hits": 5000}
]
```

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query=*' \
  "$VM_LOGS_URL/select/logsql/stream_field_values?start=2026-03-07T00:00:00Z&field=namespace" | jq '.[] | .value'
```

### GET/POST /select/logsql/streams — Log Streams

List log stream identifiers matching the query.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | LogsQL query |
| `start` | Yes | RFC3339 | - | Start of time range |
| `end` | No | RFC3339 | now | End of time range |
| `limit` | No | integer | - | Max streams to return |

Response:
```json
[
  {"value": "{namespace=\"myapp\",pod=\"myapp-abc123\",container=\"app\"}", "hits": 5000}
]
```

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"}' \
  "$VM_LOGS_URL/select/logsql/streams?start=2026-03-07T00:00:00Z&limit=20" | jq .
```

### GET/POST /select/logsql/stream_ids — Stream IDs

List internal stream IDs.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `query` | Yes | string | - | LogsQL query |
| `start` | Yes | RFC3339 | - | Start of time range |
| `end` | No | RFC3339 | now | End of time range |

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"}' \
  "$VM_LOGS_URL/select/logsql/stream_ids?start=2026-03-07T00:00:00Z" | jq .
```

## HTTP Method and Content-Type Summary

| Endpoint | GET | POST | POST Content-Type |
|----------|-----|------|-------------------|
| `/select/logsql/query` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/select/logsql/stats_query` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/select/logsql/stats_query_range` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/select/logsql/hits` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/select/logsql/facets` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/select/logsql/field_names` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/select/logsql/field_values` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/select/logsql/streams` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/select/logsql/stream_field_names` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/select/logsql/stream_field_values` | Yes | Yes | `application/x-www-form-urlencoded` |
| `/select/logsql/stream_ids` | Yes | Yes | `application/x-www-form-urlencoded` |

All endpoints accept both GET and POST. For POST, use `--data-urlencode` with curl to properly encode LogsQL queries containing special characters.

## Timestamp Format

VictoriaLogs uses RFC3339 timestamps exclusively:
- Format: `2026-03-07T09:00:00Z`
- Duration strings for `step`: `5m`, `1h`, `30s`
- Unix timestamps are NOT supported

