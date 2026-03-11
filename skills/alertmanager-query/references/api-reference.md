# AlertManager API v2 Reference

Full endpoint details for Prometheus-compatible AlertManager HTTP API v2.

Base URL: `$VM_ALERTMANAGER_URL`
- Prod: `https://alertmanager.example.com`
- Local: N/A (typically not deployed locally)

Source: Prometheus AlertManager OpenAPI v2 specification.

## Endpoint Summary

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v2/alerts` | GET | List alerts with filters |
| `/api/v2/alerts` | POST | Create/update alerts |
| `/api/v2/silences` | GET | List silences |
| `/api/v2/silences` | POST | Create silence |
| `/api/v2/silence/{silenceID}` | GET | Get specific silence |
| `/api/v2/silence/{silenceID}` | DELETE | Expire/delete silence |

## Endpoints

### GET /api/v2/alerts

List alerts with optional filters.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `active` | bool | true | Include active alerts |
| `silenced` | bool | true | Include silenced alerts |
| `inhibited` | bool | true | Include inhibited alerts |
| `unprocessed` | bool | true | Include unprocessed alerts |
| `filter` | string[] | - | Label matcher expressions (e.g., `alertname="Foo"`) |
| `receiver` | string | - | Regex to match receiver name |

**Response:** Array of `gettableAlert` objects.

```json
[
  {
    "annotations": {"summary": "High memory usage"},
    "endsAt": "2026-03-07T12:00:00.000Z",
    "fingerprint": "abc123",
    "receivers": [{"name": "slack-critical"}],
    "startsAt": "2026-03-07T10:00:00.000Z",
    "status": {
      "inhibitedBy": [],
      "silencedBy": [],
      "state": "active"
    },
    "updatedAt": "2026-03-07T10:05:00.000Z",
    "generatorURL": "http://vmalert:8880/...",
    "labels": {
      "alertname": "HighMemory",
      "namespace": "myapp",
      "severity": "warning"
    }
  }
]
```

**Alert states:** `active`, `suppressed` (silenced or inhibited), `unprocessed`

**Example:**

```bash
# All active, non-silenced alerts
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_ALERTMANAGER_URL/api/v2/alerts?active=true&silenced=false&inhibited=false" | jq .

# Filter by label
curl -s -G ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'filter=severity="critical"' \
  "$VM_ALERTMANAGER_URL/api/v2/alerts" | jq .

# Multiple filters
curl -s -G ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  --data-urlencode 'filter=alertname="HighMemory"' \
  --data-urlencode 'filter=namespace="production"' \
  "$VM_ALERTMANAGER_URL/api/v2/alerts" | jq .
```

### POST /api/v2/alerts

Create or update alerts programmatically.

**Content-Type:** `application/json`

**Request Body:** Array of `postableAlert` objects:

```json
[
  {
    "labels": {"alertname": "TestAlert", "severity": "info"},
    "annotations": {"summary": "Test alert from CLI"},
    "startsAt": "2026-03-07T10:00:00Z",
    "endsAt": "2026-03-07T12:00:00Z",
    "generatorURL": ""
  }
]
```

**Response:** Empty body on success (HTTP 200).

**Notes:** Rarely used directly — alerts typically come from VMAlert/Prometheus. Useful for testing alert routing.

### GET /api/v2/silences

List all silences.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `filter` | string[] | Matcher expressions to filter silences |

**Response:** Array of `gettableSilence` objects.

```json
[
  {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": {"state": "active"},
    "updatedAt": "2026-03-07T10:00:00.000Z",
    "comment": "Maintenance window",
    "createdBy": "claude",
    "endsAt": "2026-03-08T00:00:00.000Z",
    "startsAt": "2026-03-07T00:00:00.000Z",
    "matchers": [
      {
        "isEqual": true,
        "isRegex": false,
        "name": "alertname",
        "value": "HighMemory"
      }
    ]
  }
]
```

**Silence states:** `active`, `pending` (future start), `expired`

**Example:**

```bash
# All silences
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_ALERTMANAGER_URL/api/v2/silences" | jq .

# Active silences only
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_ALERTMANAGER_URL/api/v2/silences" | jq '[.[] | select(.status.state == "active")]'
```

### POST /api/v2/silences

Create a new silence.

**Content-Type:** `application/json`

**Request Body:** `postableSilence` object:

```json
{
  "matchers": [
    {
      "name": "alertname",
      "value": "HighMemory",
      "isRegex": false,
      "isEqual": true
    }
  ],
  "startsAt": "2026-03-07T00:00:00Z",
  "endsAt": "2026-03-08T00:00:00Z",
  "createdBy": "claude",
  "comment": "Maintenance window"
}
```

**Matcher fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Label name to match |
| `value` | string | Value to match (exact or regex) |
| `isRegex` | bool | If true, `value` is treated as regex |
| `isEqual` | bool | If true, match equals; if false, match not-equals |

**Response:**

```json
{
  "silenceID": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Notes:**
- To update an existing silence, include `"id": "existing-uuid"` in the request body
- `startsAt` and `endsAt` are RFC3339 timestamps
- At least one matcher is required

**Example:**

```bash
# Create a 2-hour silence for a specific alert
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  -X POST -H "Content-Type: application/json" \
  -d '{
    "matchers": [{"name": "alertname", "value": "HighMemory", "isRegex": false, "isEqual": true}],
    "startsAt": "2026-03-07T10:00:00Z",
    "endsAt": "2026-03-07T12:00:00Z",
    "createdBy": "claude",
    "comment": "Investigating memory issue"
  }' \
  "$VM_ALERTMANAGER_URL/api/v2/silences" | jq .

# Regex silence — silence all alerts matching pattern
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  -X POST -H "Content-Type: application/json" \
  -d '{
    "matchers": [{"name": "alertname", "value": "High.*", "isRegex": true, "isEqual": true}],
    "startsAt": "2026-03-07T10:00:00Z",
    "endsAt": "2026-03-07T12:00:00Z",
    "createdBy": "claude",
    "comment": "Silencing all High* alerts during maintenance"
  }' \
  "$VM_ALERTMANAGER_URL/api/v2/silences" | jq .
```

### GET /api/v2/silence/{silenceID}

Get a specific silence by ID.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `silenceID` | string (UUID) | Silence identifier |

**Response:** Single `gettableSilence` object (same format as list response item).

**Example:**

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_ALERTMANAGER_URL/api/v2/silence/a1b2c3d4-e5f6-7890-abcd-ef1234567890" | jq .
```

### DELETE /api/v2/silence/{silenceID}

Expire (delete) a silence.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `silenceID` | string (UUID) | Silence identifier |

**Response:** Empty body on success (HTTP 200).

**Example:**

```bash
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  -X DELETE \
  "$VM_ALERTMANAGER_URL/api/v2/silence/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```


## HTTP Methods and Content-Type Summary

| Endpoint | Method | Content-Type (Request) | Content-Type (Response) |
|----------|--------|----------------------|------------------------|
| `/api/v2/alerts` | GET | N/A | application/json |
| `/api/v2/alerts` | POST | application/json | N/A (empty body) |
| `/api/v2/silences` | GET | N/A | application/json |
| `/api/v2/silences` | POST | application/json | application/json |
| `/api/v2/silence/{id}` | GET | N/A | application/json |
| `/api/v2/silence/{id}` | DELETE | N/A | N/A (empty body) |

## Auth Pattern

```bash
# Conditional auth (works for both prod and local)
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} "$VM_ALERTMANAGER_URL/api/v2/alerts"

# POST with auth and JSON body
curl -s ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  -X POST -H "Content-Type: application/json" \
  -d '{"matchers": [...], "startsAt": "...", "endsAt": "...", "createdBy": "...", "comment": "..."}' \
  "$VM_ALERTMANAGER_URL/api/v2/silences"
```

## Availability and Fallback

AlertManager runs as an in-cluster pod. It may be unavailable due to:
- Pod crashloop or OOM
- DNS resolution failure
- Not deployed in local/dev environments

**Fallback strategy:**
- For alert data: use `$VM_METRICS_URL/api/v1/alerts` (VictoriaMetrics built-in alert API)
- For alert rules: use `$VM_METRICS_URL/api/v1/rules`
- Silences and inhibition state have no fallback — they are AlertManager-only features

**Connectivity check:**

```bash
curl -sf -o /dev/null -w "%{http_code}" ${VM_AUTH_HEADER:+-H "$VM_AUTH_HEADER"} \
  "$VM_ALERTMANAGER_URL/api/v2/alerts" && echo " OK" || echo " UNREACHABLE"
```

## Timestamp Format

All timestamps use RFC3339 format: `2026-03-07T00:00:00Z`

Fields using timestamps: `startsAt`, `endsAt`, `updatedAt`

## Filter Syntax

The `filter` query parameter accepts PromQL-style label matchers:

| Matcher | Description | Example |
|---------|-------------|---------|
| `=` | Exact match | `alertname="HighMemory"` |
| `!=` | Not equal | `severity!="info"` |
| `=~` | Regex match | `alertname=~"High.*"` |
| `!~` | Negative regex | `namespace!~"kube-.*"` |

Multiple filters can be passed as separate `filter` query params — they are ANDed together.
