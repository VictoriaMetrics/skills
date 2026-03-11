# VictoriaTraces Jaeger-compatible HTTP API Reference

Full endpoint documentation for VictoriaTraces trace queries. Verified against live VictoriaTraces instance and Jaeger API specification (2026-03-07).

Base URL: `$VM_TRACES_URL`
- Prod: `https://vtselect.example.com/select/jaeger`
- Local: `http://localhost:10428/select/jaeger`

IMPORTANT: The Jaeger API prefix `/select/jaeger` is included in `$VM_TRACES_URL`. All endpoints below are relative to this base.

## Discovery Endpoints

### GET /api/services — List Services

List all traced service names. No parameters.

Response:
```json
{
  "data": ["frontend", "api-gateway", "user-service", "order-service"],
  "errors": null,
  "limit": 0,
  "offset": 0,
  "total": 0
}
```

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/services" | jq '.data[]'
```

### GET /api/services/{service}/operations — Service Operations

List operations for a specific service. `service` is a PATH parameter.

Response:
```json
{
  "data": ["GET /api/health", "POST /api/orders", "GET /api/users/{id}"],
  "errors": null,
  "limit": 0,
  "offset": 0,
  "total": 0
}
```

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/services/my-service/operations" | jq '.data[]'
```

Note: Service names with special characters should be URL-encoded in the path.

## Query Endpoints

### GET /api/traces — Search Traces

Search for traces matching criteria. `service` is required.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `service` | Yes | string | - | Service name |
| `operation` | No | string | - | Operation name filter |
| `start` | No | Unix microseconds | - | Start of time range (16 digits) |
| `end` | No | Unix microseconds | - | End of time range (16 digits) |
| `limit` | No | integer | 20 | Max number of traces |
| `minDuration` | No | string | - | Minimum trace duration (e.g., `1s`, `500ms`, `100us`) |
| `maxDuration` | No | string | - | Maximum trace duration |
| `tags` | No | string | - | Tag filters — Jaeger JSON format `{"key":"value"}` or VictoriaTraces extended format `key=value resource_attr:key=value` |

Response:
```json
{
  "data": [
    {
      "traceID": "abc123def456789",
      "spans": [
        {
          "traceID": "abc123def456789",
          "spanID": "span001",
          "operationName": "GET /api/health",
          "references": [],
          "startTime": 1709769600000000,
          "duration": 15234,
          "tags": [
            {"key": "http.method", "type": "string", "value": "GET"},
            {"key": "http.status_code", "type": "int64", "value": 200},
            {"key": "error", "type": "bool", "value": false}
          ],
          "logs": [],
          "processID": "p1",
          "warnings": null
        }
      ],
      "processes": {
        "p1": {
          "serviceName": "my-service",
          "tags": [
            {"key": "hostname", "type": "string", "value": "pod-abc123"}
          ]
        }
      },
      "warnings": null
    }
  ],
  "errors": null,
  "limit": 0,
  "offset": 0,
  "total": 0
}
```

Key response details:
- `spans[].startTime` — Unix MICROSECONDS (not milliseconds)
- `spans[].duration` — MICROSECONDS
- `spans[].references` — parent span references (`CHILD_OF`, `FOLLOWS_FROM`)
- `spans[].processID` — maps to `processes` object for service name
- `spans[].tags` — key-value pairs with type information
- `spans[].logs` — span events/logs with timestamp and fields

Examples:
```bash
# Basic search — timestamps in microseconds (16 digits)
END_US=$(date +%s%6N)
START_US=$((END_US - 3600000000))
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/traces?service=my-service&start=${START_US}&end=${END_US}&limit=20" | jq .

# With operation filter
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/traces?service=my-service&operation=GET+/api/health&start=${START_US}&end=${END_US}&limit=10" | jq .

# With duration filter
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/traces?service=my-service&start=${START_US}&end=${END_US}&minDuration=1s&maxDuration=10s&limit=20" | jq .

# With tag filter — Jaeger JSON format (URL-encoded)
curl -s -G ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'tags={"http.status_code":"500"}' \
  "$VM_TRACES_URL/api/traces?service=my-service&start=${START_US}&end=${END_US}&limit=20" | jq .

# With tag filter — VictoriaTraces extended format (key=value, space-separated)
curl -s -G ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'tags=error=unset resource_attr:service.namespace=production' \
  "$VM_TRACES_URL/api/traces?service=my-service&start=${START_US}&end=${END_US}&limit=20" | jq .
```

### GET /api/traces/{traceID} — Get Trace by ID

Retrieve a complete trace by its trace ID. No query parameters.

Response: Same structure as trace search but with a single trace in `data` array.

Error response (trace not found):
```json
{
  "data": [],
  "errors": [{"code": 404, "msg": "trace not found"}],
  "limit": 0,
  "offset": 0,
  "total": 0
}
```

Note: This returns an HTTP 200 with errors in the response body, NOT an HTTP 404 status code.

Example:
```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/traces/abc123def456789" | jq .

# Check if trace was found
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/traces/abc123def456789" | jq 'if .errors then "NOT FOUND: " + .errors[0].msg else "Found: " + (.data[0].spans | length | tostring) + " spans" end'
```

## Dependency Endpoint

### GET /api/dependencies — Service Dependencies

Get service dependency graph showing call relationships.

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `endTs` | Yes | Unix milliseconds | - | End timestamp for dependency calculation |
| `lookback` | Yes | Unix milliseconds | - | Duration to look back from `endTs` (e.g., `3600000` = 1 hour) |

Response:
```json
{
  "data": [
    {"parent": "api-gateway", "child": "user-service", "callCount": 1523},
    {"parent": "api-gateway", "child": "order-service", "callCount": 892},
    {"parent": "order-service", "child": "payment-service", "callCount": 445}
  ],
  "errors": null,
  "limit": 0,
  "offset": 0,
  "total": 0
}
```

Example:
```bash
END_MS=$(date +%s%3N)
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/dependencies?endTs=${END_MS}&lookback=3600000" | jq '.data[]'

# Last 24 hours
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/dependencies?endTs=${END_MS}&lookback=86400000" | jq '.data[] | "\(.parent) -> \(.child) (\(.callCount) calls)"'
```

## HTTP Method and Content-Type Summary

| Endpoint | GET | POST | POST Content-Type |
|----------|-----|------|-------------------|
| `/api/services` | Yes | No | N/A |
| `/api/services/{service}/operations` | Yes | No | N/A |
| `/api/traces` | Yes | Yes | `application/json` |
| `/api/traces/{traceID}` | Yes | No | N/A |
| `/api/dependencies` | Yes | No | N/A |

GET with query parameters is sufficient for all endpoints. POST is only supported for trace search.

## Timestamp Format

Trace search and dependencies use DIFFERENT timestamp units:

| Parameter | Used In | Unit | Digits | Example |
|-----------|---------|------|--------|---------|
| `start` | traces search | Microseconds | 16 | `1709769600000000` |
| `end` | traces search | Microseconds | 16 | `1709769600000000` |
| `endTs` | dependencies | Milliseconds | 13 | `1709769600000` |
| `lookback` | dependencies | Milliseconds | 13 | `3600000` (= 1 hour) |
| `minDuration` | traces search | String duration | - | `1s`, `500ms`, `100us` |
| `maxDuration` | traces search | String duration | - | `10s`, `5s` |

Response timestamps:
- `spans[].startTime` — Unix MICROSECONDS
- `spans[].duration` — MICROSECONDS

Conversion helpers:
```bash
# Current time in microseconds (for trace search)
date +%s%6N

# N hours ago in microseconds
echo $(($(date +%s%6N) - N * 3600000000))

# Specific time to microseconds (GNU date)
date -d "2026-03-07T09:00:00Z" +%s%6N

# Current time in milliseconds (for dependencies)
date +%s%3N
```


## Jaeger Span Reference Types

Spans link to parent spans via `references`:
```json
{
  "references": [
    {"refType": "CHILD_OF", "traceID": "abc123", "spanID": "span001"}
  ]
}
```

- `CHILD_OF` — standard parent-child relationship
- `FOLLOWS_FROM` — causal but not blocking dependency
- Root spans have empty or null `references`

## Common jq Patterns

```bash
# Summarize a trace: service calls and durations
... | jq '.data[] | . as $trace | {traceID: .traceID, services: [.spans[] | {op: .operationName, svc: $trace.processes[.processID].serviceName, ms: (.duration / 1000)}]}'

# Find the critical path (longest spans)
... | jq '.data[].spans | sort_by(-.duration) | .[:5] | .[] | {op: .operationName, duration_ms: (.duration / 1000)}'

# Count spans per service
... | jq '.data[] | . as $trace | {traceID: .traceID, by_service: ([.spans[] | $trace.processes[.processID].serviceName] | group_by(.) | map({service: .[0], count: length}))}'
```
