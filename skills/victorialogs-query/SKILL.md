---
name: victorialogs-query
description: >
  Query VictoriaLogs via curl. Use when searching logs with LogsQL, running log stats queries,
  discovering log fields/streams, analyzing log hit patterns, or exploring log facets.
  Triggers on: log queries, LogsQL, log search, log stats, field discovery, stream discovery,
  log facets, log hits, log field values.
allowed-tools: Bash(curl:*)
---

# VictoriaLogs Query

Query VictoriaLogs HTTP API directly via curl. Covers log search, stats queries, field/stream discovery, hits analysis, and facets.

## Environment

```bash
# $VM_LOGS_URL - base URL
#   Example: export VM_LOGS_URL="https://vlselect.example.com"
# $VM_AUTH_HEADER - auth header (set for prod, empty for local)
```

## Auth Pattern

All curl commands use conditional auth:

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_LOGS_URL/select/logsql/query?query=*&start=2026-03-07T00:00:00Z&limit=10"
```

When `VM_AUTH_HEADER` is empty, `-H` flag is omitted automatically.

## Critical Rules

- ALWAYS pass `start` on ALL VictoriaLogs endpoints — omitting it scans ALL stored data (extremely expensive). Not technically required by the API, but omitting it is almost never what you want.
- `stats_query` uses `time` (defaults to now if omitted), `stats_query_range` uses `start`/`end`/`step`
- `step` is required for `hits` endpoint
- `/select/logsql/query` returns JSON Lines (one JSON object per line), NOT a JSON array
- LogsQL queries with special characters MUST be URL-encoded (use `--data-urlencode` for POST)
- `stats_query` and `stats_query_range` queries MUST contain a `| stats` pipe

## Core Endpoints

### Log Query

```bash
# Basic query (last hour, limit 100)
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"} error' \
  "$VM_LOGS_URL/select/logsql/query?start=2026-03-07T00:00:00Z&limit=100"

# With time range and field selection
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"} error' \
  "$VM_LOGS_URL/select/logsql/query?start=2026-03-07T00:00:00Z&end=2026-03-07T12:00:00Z&limit=50&fields=_time,_msg,level"
```

Parameters: `query` (required), `start` (required, RFC3339), `end`, `limit`, `offset`, `fields` (comma-separated), `timeout`

Response: JSON Lines (one JSON object per line). Pipe through `jq -s .` to collect into array, or process line-by-line.

### Stats Query (Instant)

```bash
# Count errors by level at a point in time
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"} | stats by (level) count() as total' \
  "$VM_LOGS_URL/select/logsql/stats_query?time=2026-03-07T09:00:00Z" | jq .
```

Parameters: `query` (required, must contain `| stats` pipe), `time` (required, RFC3339), `start` (optional, alternative to `time`).

Response: Prometheus-compatible JSON format.

### Stats Query Range

```bash
# Error count over time with 1h steps
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"} error | stats count() as total' \
  "$VM_LOGS_URL/select/logsql/stats_query_range?start=2026-03-07T00:00:00Z&end=2026-03-07T12:00:00Z&step=1h" | jq .
```

Parameters: `query` (required, must contain `| stats` pipe), `start` (required), `end`, `step` (e.g., `1h`, `5m`)

Response: Prometheus matrix format.

### Hits (Log Volume)

```bash
# Log volume over time
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"}' \
  "$VM_LOGS_URL/select/logsql/hits?start=2026-03-07T00:00:00Z&end=2026-03-07T12:00:00Z&step=1h" | jq .
```

Parameters: `query` (required), `start` (required), `end`, `step` (required), `field` (optional, group by field)

### Facets (Best Discovery Tool)

```bash
# Discover field value distributions
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"}' \
  "$VM_LOGS_URL/select/logsql/facets?start=2026-03-07T00:00:00Z&end=2026-03-07T12:00:00Z" | jq .
```

Parameters: `query` (required), `start` (required), `end`. Returns most frequent values for ALL fields in one call.

## Discovery Endpoints

### Field Names and Values

```bash
# Discover non-stream field names
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"}' \
  "$VM_LOGS_URL/select/logsql/field_names?start=2026-03-07T00:00:00Z" | jq .

# Get values for a specific field
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"}' \
  "$VM_LOGS_URL/select/logsql/field_values?start=2026-03-07T00:00:00Z&field=level&limit=20" | jq .
```

### Stream Fields

```bash
# Discover stream field names (e.g., namespace, pod)
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query=*' \
  "$VM_LOGS_URL/select/logsql/stream_field_names?start=2026-03-07T00:00:00Z" | jq .

# Get values for a stream field
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query=*' \
  "$VM_LOGS_URL/select/logsql/stream_field_values?start=2026-03-07T00:00:00Z&field=namespace" | jq .
```

### Streams and Stream IDs

```bash
# List log stream identifiers
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"}' \
  "$VM_LOGS_URL/select/logsql/streams?start=2026-03-07T00:00:00Z&limit=20" | jq .

# List stream IDs
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"}' \
  "$VM_LOGS_URL/select/logsql/stream_ids?start=2026-03-07T00:00:00Z" | jq .
```

## LogsQL Quick Reference

LogsQL is space-separated (AND by default). Pipes use `|`.

```logsql
# Stream filter (fast, use for namespace/pod selection)
{namespace="myapp"}

# Word filter (matches full words in _msg)
{namespace="myapp"} error

# Multiple words (AND)
{namespace="myapp"} error timeout

# OR filter
{namespace="myapp"} (error OR warning)

# Regex filter on _msg
{namespace="myapp"} ~"err|warn"

# Case-insensitive regex
{namespace="myapp"} ~"(?i)error"

# Field-specific filter
{namespace="myapp"} level:error

# Time filter (alternative to API start/end params)
{namespace="myapp"} _time:1h error

# Negation
{namespace="myapp"} error -"expected error"

# Stats pipe
{namespace="myapp"} _time:1h | stats by (level) count() as total

# Sort pipe
{namespace="myapp"} error | sort by (_time)

# Top pipe
{namespace="myapp"} _time:1h | top 10 (level)
```

Common mistakes:

- `| grep` does NOT exist. Use word filters or `~"regex"`.
- `| filter` is a valid pipe but ONLY after `| stats` for filtering aggregated results.
- Time ranges go in API `start`/`end` params OR `_time:` filter, NOT both.
- Stream field names depend on your ingestion config. ALWAYS discover them first.
- Searching "error" without filtering vmselect: vmselect logs contain PromQL text with "error" — add `-"vm_slow_query_stats"` to exclude.

## Timestamp Format

All times use RFC3339 format: `2026-03-07T09:00:00Z`. Unix timestamps are NOT supported by VictoriaLogs.

## Response Parsing (jq)

```bash
# Collect JSON Lines into array
... | jq -s .

# Extract message and timestamp from query results
... | jq -s '.[] | {time: ._time, msg: ._msg}'

# Count results from JSON Lines
... | jq -s 'length'

# Extract specific fields
... | jq -s '.[] | {time: ._time, level: .level, msg: ._msg}'

# Stats query — extract metric values
... | jq '.data.result[] | {metric: .metric, value: .value[1]}'

# Stats range query — extract time series
... | jq '.data.result[] | {metric: .metric, values: .values}'

# Facets — list fields and top values
... | jq '.[] | {field: .name, values: [.values[] | .value]}'
```

## Common Patterns

```bash
# Quick error check for a namespace (last hour)
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"} error' \
  "$VM_LOGS_URL/select/logsql/query?start=$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)&limit=20"

# Error rate over time
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query={namespace="myapp"} error | stats count() as errors' \
  "$VM_LOGS_URL/select/logsql/stats_query_range?start=2026-03-07T00:00:00Z&step=1h" | jq .

# Discover all namespaces with logs
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query=*' \
  "$VM_LOGS_URL/select/logsql/stream_field_values?start=2026-03-07T00:00:00Z&field=namespace" | jq .

# Search by trace ID in logs
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'query=trace_id:"abc123def456"' \
  "$VM_LOGS_URL/select/logsql/query?start=2026-03-07T00:00:00Z&limit=50"
```

## Environment Switching

```bash
# Check current environment
echo "VM_LOGS_URL: $VM_LOGS_URL"
echo "VM_AUTH_HEADER: ${VM_AUTH_HEADER:+(set)${VM_AUTH_HEADER-(empty)}}"
```

## Important Notes

- POST is preferred for queries with special characters — use `--data-urlencode` to avoid URL encoding issues
- ALL endpoints accept both GET and POST with `application/x-www-form-urlencoded`
- `field` parameter is required for `field_values` and `stream_field_values` endpoints
- `facets` is the best single-call discovery tool — returns all field distributions at once
- Do NOT confuse `stats_query` (instant, uses `time`) with `stats_query_range` (range, uses `start`/`end`/`step`)
- For full endpoint details, parameters, and response formats, see `references/api-reference.md`
