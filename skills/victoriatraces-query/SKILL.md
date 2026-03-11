---
name: victoriatraces-query
description: >
  Query VictoriaTraces via curl using the Jaeger-compatible API. Use when discovering traced services
  and operations, searching traces by service/operation/duration/tags, retrieving traces by ID,
  or mapping service dependencies. Triggers on: trace queries, span search, trace ID lookup,
  service discovery, operation discovery, service dependencies, distributed tracing, Jaeger API.
allowed-tools: Bash(curl:*)
---

# VictoriaTraces Query

Query VictoriaTraces Jaeger-compatible HTTP API directly via curl. Covers service/operation discovery, trace search, trace retrieval by ID, and dependency mapping.

## Environment

```bash
# $VM_TRACES_URL - base URL including /select/jaeger prefix
#   Example: export VM_TRACES_URL="https://vtselect.example.com/select/jaeger"
# $VM_AUTH_HEADER - auth header (set for prod, empty for local)
```

IMPORTANT: The Jaeger API lives under `/select/jaeger/api/...`, NOT root `/api/...`. The `$VM_TRACES_URL` env var already includes the `/select/jaeger` prefix, so all endpoints below use `$VM_TRACES_URL/api/...`.

## Auth Pattern

All curl commands use conditional auth:

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/services" | jq .
```

When `VM_AUTH_HEADER` is empty, `-H` flag is omitted automatically.

## Critical Rules

- Trace search `start`/`end` use Unix MICROSECONDS (16 digits, e.g., `1709769600000000`)
- Dependencies `endTs`/`lookback` use Unix MILLISECONDS (13 digits, e.g., `1709769600000`)
- `service` is required for trace search — you must know the service name first
- `minDuration`/`maxDuration` are string durations (e.g., `"1s"`, `"500ms"`)
- Trace IDs not found return 404 in the `errors` array, not an HTTP 404
- Trace search with time ranges outside retention returns plain text error, not JSON — handle gracefully
- Always discover services first, then operations, then search traces

## Core Endpoints

### List Services

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/services" | jq '.data[]'
```

No parameters. Returns all traced service names. Always start here to discover what's available.

### Service Operations

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/services/my-service/operations" | jq '.data[]'
```

`service` is a PATH parameter. Returns operation names for the given service.

### Search Traces

```bash
# Basic search (last hour, limit 20) — timestamps in microseconds (16 digits)
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/traces?service=my-service&start=$(($(date +%s%6N) - 3600000000))&end=$(date +%s%6N)&limit=20" | jq .

# With operation and duration filter
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/traces?service=my-service&operation=GET+/api/health&start=$(($(date +%s%6N) - 3600000000))&end=$(date +%s%6N)&minDuration=100ms&limit=20" | jq .

# With tag filter (Jaeger JSON format)
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/traces?service=my-service&start=$(($(date +%s%6N) - 3600000000))&end=$(date +%s%6N)&tags=%7B%22http.status_code%22%3A%22500%22%7D&limit=20" | jq .

# With tag filter (VictoriaTraces extended format — key=value pairs, space-separated)
curl -s -G ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'tags=http.status_code=500 resource_attr:service.namespace=production' \
  "$VM_TRACES_URL/api/traces?service=my-service&start=$(($(date +%s%6N) - 3600000000))&end=$(date +%s%6N)&limit=20" | jq .
```

Parameters: `service` (required), `operation`, `start` (Unix µs), `end` (Unix µs), `limit`, `minDuration` (e.g., `1s`), `maxDuration`, `tags` (URL-encoded JSON object or VictoriaTraces key=value format)

### Get Trace by ID

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/traces/abc123def456789" | jq .
```

Returns full trace with all spans. If trace not found, response contains `"errors": [{"code": 404, "msg": "trace not found"}]`.

### Service Dependencies

```bash
# Dependencies for the last hour
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/dependencies?endTs=$(date +%s%3N)&lookback=3600000" | jq '.data[]'
```

Parameters: `endTs` (Unix ms, required), `lookback` (duration in ms, required). Returns edges between services showing call relationships.

## Timestamp Format

Trace search and dependencies use DIFFERENT timestamp units:

| Endpoint | Parameter | Unit | Digits | Example |
|----------|-----------|------|--------|---------|
| `/api/traces` | `start`, `end` | Microseconds | 16 | `1709769600000000` |
| `/api/dependencies` | `endTs` | Milliseconds | 13 | `1709769600000` |
| `/api/dependencies` | `lookback` | Milliseconds | 13 | `3600000` (1 hour) |

```bash
# Current time in microseconds (for trace search)
date +%s%6N

# 1 hour ago in microseconds
echo $(($(date +%s%6N) - 3600000000))

# Specific time to microseconds (GNU date)
date -d "2026-03-07T09:00:00Z" +%s%6N

# Current time in milliseconds (for dependencies)
date +%s%3N

# Duration values for minDuration/maxDuration are strings: "1s", "500ms", "100us"
# Duration value for lookback is ms number: 3600000 = 1 hour
```

## Response Parsing (jq)

```bash
# List service names
... | jq '.data[]'

# Extract trace IDs from search results
... | jq '.data[] | .traceID'

# Get span count per trace
... | jq '.data[] | {traceID: .traceID, spans: (.spans | length)}'

# Extract spans with duration > 1s (duration is in microseconds)
... | jq '.data[].spans[] | select(.duration > 1000000) | {operation: .operationName, duration_ms: (.duration / 1000)}'

# Get root span of each trace
... | jq '.data[] | .spans[] | select(.references == null or (.references | length) == 0) | {traceID: .traceID, operation: .operationName, service: .processID}'

# Extract service-to-service calls from dependencies
... | jq '.data[] | "\(.parent) -> \(.child) (\(.callCount) calls)"'

# Get all tags from a span
... | jq '.data[].spans[] | {operation: .operationName, tags: [.tags[] | {(.key): .value}] | add}'

# Find error spans
... | jq '.data[].spans[] | select(.tags[] | select(.key == "error" and .value == true)) | {traceID: .traceID, operation: .operationName}'
```

## Common Patterns

```bash
# Full discovery workflow: services -> operations -> traces
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} "$VM_TRACES_URL/api/services" | jq '.data[]'
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} "$VM_TRACES_URL/api/services/my-service/operations" | jq '.data[]'
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} "$VM_TRACES_URL/api/traces?service=my-service&start=$(($(date +%s%6N) - 3600000000))&end=$(date +%s%6N)&limit=10" | jq '.data[] | .traceID'

# Find slow traces (> 5 seconds)
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/traces?service=my-service&start=$(($(date +%s%6N) - 3600000000))&end=$(date +%s%6N)&minDuration=5s&limit=20" | jq '.data[] | {traceID: .traceID, spans: (.spans | length)}'

# Look up a trace ID found in logs
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/traces/abc123def456789" | jq '.data[].spans[] | {operation: .operationName, duration_ms: (.duration / 1000), service: .processID}'

# Map service dependencies (last 24 hours) — dependencies use milliseconds
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_TRACES_URL/api/dependencies?endTs=$(date +%s%3N)&lookback=86400000" | jq '.data[]'
```

## Environment Switching

```bash
# Check current environment
echo "VM_TRACES_URL: $VM_TRACES_URL"
if [ -n "${VM_AUTH_HEADER-}" ]; then
  echo "VM_AUTH_HEADER: (set)"
else
  echo "VM_AUTH_HEADER: (unset)"
fi
```

## Important Notes

- The Jaeger API prefix `/select/jaeger` is included in `$VM_TRACES_URL` — do NOT add it again
- `tags` parameter supports both Jaeger JSON format (`{"key":"value"}`) and VictoriaTraces extended format (`key=value resource_attr:key=value scope_attr:key=value`)
- Span durations in responses are in MICROSECONDS (not milliseconds)
- Process info is referenced by `processID` in spans, mapped in the trace's `processes` object
- GET is sufficient for all endpoints — POST also works for trace search
- For full endpoint details, parameters, and response formats, see `references/api-reference.md`
