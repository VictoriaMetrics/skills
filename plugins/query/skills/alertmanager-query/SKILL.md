---
name: alertmanager-query
description: >
  Query AlertManager via curl using the v2 API. Use when listing active/silenced alerts, creating/managing silences,
  or checking alert inhibition state. Triggers on: alertmanager, silences, silence alerts, alert filters,
  alert inhibition, alertmanager API, create silence, delete silence.
allowed-tools: Bash(curl:*), Bash(jq:*)
---

# AlertManager Query (API v2)

Query Prometheus-compatible AlertManager HTTP API v2 directly via curl. Covers alert listing with filters, silence management (list, create, get, delete), and alert state inspection.

## Availability Warning

AlertManager runs as an in-cluster pod and may be unavailable (crashloop, DNS failure, not deployed locally). Always check connectivity first. When AlertManager is down, ask vmalert for the firing and pending alerts:

```bash
# Fallback: firing/pending alerts from vmalert
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VM_ALERT_URL/api/v1/alerts" | jq '.data.alerts[]'
```

`$VM_METRICS_URL/api/v1/alerts` gives the same list only when VictoriaMetrics runs with `-vmalert.proxyURL`. Without that flag it answers with an empty list.

AlertManager provides what VM alerts cannot: silences, inhibition state, and alert routing.

## Environment

```bash
# $VM_ALERTMANAGER_URL - base URL
#   Remote: export VM_ALERTMANAGER_URL="https://alertmanager.example.com"
#   Local:  export VM_ALERTMANAGER_URL="http://localhost:9093"
# $VM_ALERT_URL - vmalert base URL, for the fallback
#   Local:  export VM_ALERT_URL="http://localhost:8880"
# $VM_CURL_CONFIG - curl config file with auth header (set for remote, unset for local)
#   Remote: export VM_CURL_CONFIG="$HOME/.config/victoriametrics/curl.conf"
#   Local:  leave unset (defaults to /dev/null - no auth)
```

## Auth Pattern

All curl commands load auth from a curl config file:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VM_ALERTMANAGER_URL/api/v2/alerts" | jq .
```

When `VM_CURL_CONFIG` is unset, curl reads `/dev/null` and sends no auth header. When set, it must point to a mode-0600 curl config file containing `header = "Authorization: Bearer <token>"`. Never print its contents.

## Core Endpoints

### List Alerts

```bash
# All alerts (active, silenced, inhibited)
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VM_ALERTMANAGER_URL/api/v2/alerts" | jq .

# Only active (not silenced, not inhibited)
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VM_ALERTMANAGER_URL/api/v2/alerts?active=true&silenced=false&inhibited=false" | jq .

# Filter by label matcher (URL-encode the matcher)
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s -G \
  --data-urlencode 'filter=alertname="HighMemory"' \
  "$VM_ALERTMANAGER_URL/api/v2/alerts" | jq .

# Filter by receiver
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VM_ALERTMANAGER_URL/api/v2/alerts?receiver=slack-critical" | jq .
```

Parameters: `active` (bool, default true), `silenced` (bool, default true), `inhibited` (bool, default true), `unprocessed` (bool, default true), `filter` (string array, matcher expressions), `receiver` (string regex)

The list holds only alerts that have not resolved. An alert leaves it once it resolves, so an empty list does not mean the alert never reached AlertManager. For past alerts, read `ALERTS`, which vmalert writes to VictoriaMetrics when it runs with `-remoteWrite.url`:

```bash
# When did HighMemory fire in the last 30 minutes (first and last firing evaluation)
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  --data-urlencode 'query=ALERTS{alertname="HighMemory", alertstate="firing"}[30m]' \
  "$VM_METRICS_URL/api/v1/query" | jq -r '.data.result[] | "\(.values[0][0] | todate) .. \(.values[-1][0] | todate)"'
```

### List Silences

```bash
# All silences
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VM_ALERTMANAGER_URL/api/v2/silences" | jq .

# Filter silences by matcher
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s -G \
  --data-urlencode 'filter=alertname="HighMemory"' \
  "$VM_ALERTMANAGER_URL/api/v2/silences" | jq .
```

Parameters: `filter` (string array, matcher expressions)

### Get Silence by ID

```bash
# Note: singular "silence" in path (not "silences")
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VM_ALERTMANAGER_URL/api/v2/silence/{silenceID}" | jq .
```

Replace `{silenceID}` with the UUID.

### Create Silence

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  -X POST -H "Content-Type: application/json" \
  -d '{
    "matchers": [
      {"name": "alertname", "value": "HighMemory", "isRegex": false, "isEqual": true}
    ],
    "startsAt": "2026-03-07T00:00:00Z",
    "endsAt": "2026-03-08T00:00:00Z",
    "createdBy": "claude",
    "comment": "Maintenance window"
  }' \
  "$VM_ALERTMANAGER_URL/api/v2/silences" | jq .
```

Returns `{"silenceID": "uuid-here"}`. Matcher fields: `name` (label name), `value` (match value), `isRegex` (bool), `isEqual` (bool — false for negative match). Times in RFC3339.

### Delete (Expire) Silence

```bash
# Note: singular "silence" in path
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  -X DELETE \
  "$VM_ALERTMANAGER_URL/api/v2/silence/{silenceID}"
```

Replace `{silenceID}` with the UUID. Returns empty body on success.

## Timestamp Format

All timestamps use RFC3339 format: `2026-03-07T00:00:00Z`

## Response Parsing (jq)

```bash
# Count alerts by state
... | jq 'group_by(.status.state) | map({state: .[0].status.state, count: length})'

# List alert names and states
... | jq '.[] | {alertname: .labels.alertname, state: .status.state, severity: .labels.severity}'

# Active silences only (not expired)
... | jq '[.[] | select(.status.state == "active")]'

# Silence details (ID, matchers, expiry)
... | jq '.[] | {id: .id, matchers: [.matchers[] | "\(.name)=\(.value)"], endsAt: .endsAt, createdBy: .createdBy}'
```

## Common Patterns

```bash
# Quick connectivity check: 200 = up, 401 or 403 = auth problem, 000 = no HTTP response (host down, DNS, TLS or timeout)
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s -o /dev/null -w "%{http_code}\n" \
  "$VM_ALERTMANAGER_URL/api/v2/alerts"

# Count firing alerts
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VM_ALERTMANAGER_URL/api/v2/alerts?active=true&silenced=false&inhibited=false" | jq 'length'

# Silence an alert for 2 hours from now
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  -X POST -H "Content-Type: application/json" \
  -d "$(jq -n --arg alert "AlertName" --arg reason "Investigation in progress" \
    '{matchers: [{name: "alertname", value: $alert, isRegex: false, isEqual: true}],
      startsAt: (now | todate), endsAt: (now + 7200 | todate), createdBy: "claude", comment: $reason}')" \
  "$VM_ALERTMANAGER_URL/api/v2/silences" | jq .

# Check if a specific alert is silenced (an inhibited alert is also "suppressed", so read silencedBy)
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s -G \
  --data-urlencode 'filter=alertname="TargetAlert"' \
  "$VM_ALERTMANAGER_URL/api/v2/alerts" | jq '[.[] | select(.status.silencedBy | length > 0)] | length'
```

## Environment Switching

```bash
# Check current environment
echo "VM_ALERTMANAGER_URL: $VM_ALERTMANAGER_URL"
echo "VM_CURL_CONFIG: ${VM_CURL_CONFIG:-(unset - no auth)}"
```

## Important Notes

- Path difference: plural `/api/v2/silences` for list/create, singular `/api/v2/silence/{id}` for get/delete
- To change a silence, POST it again with its `id`. If the matchers change, AlertManager expires the old silence and returns a new ID: use the new one from then on
- POST endpoints require `Content-Type: application/json`
- DELETE returns empty body on success (HTTP 200)
- `filter` parameter uses PromQL-style matchers: `alertname="Foo"`, `severity=~"critical|warning"`
- AlertManager may be down: fall back to `$VM_ALERT_URL/api/v1/alerts`
- For full endpoint details, parameters, and response formats, see `references/api-reference.md`
