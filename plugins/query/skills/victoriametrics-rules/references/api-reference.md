# vmalert HTTP API reference

Every `/api/v1/...` path below is also served under a `/vmalert` prefix by default, so
`/api/v1/rules` and `/vmalert/api/v1/rules` are the same endpoint. `/flags`, `/metrics` and
`/-/reload` have no `/vmalert` form and answer `400` with it. The datasource paths, such as
`/api/v1/query_range`, are not served either. Use the bare form unless vmalert sits behind a
path-rewriting proxy.

All responses in this file were captured from a running vmalert. Field names are exact.

## Contents

- [GET /api/v1/rules](#get-apiv1rules) - every group and rule, with state and health
- [GET /api/v1/rule](#get-apiv1rule) - one rule, plus its per-evaluation history
- [GET /api/v1/alerts](#get-apiv1alerts) - active alerts with rendered annotations
- [GET /api/v1/alert](#get-apiv1alert) - one alert
- [GET /api/v1/group](#get-apiv1group) - one group
- [GET /api/v1/notifiers](#get-apiv1notifiers) - notifier targets and their last error
- [POST /-/reload](#post--reload) - re-read the rule files
- [GET /flags](#get-flags) - the flags vmalert was started with
- [ALERTS and ALERTS_FOR_STATE](#alerts-and-alerts_for_state) - the alert state vmalert writes
- [Rule and group fields](#rule-and-group-fields) - the YAML side

## GET /api/v1/rules

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body "$VM_ALERT_URL/api/v1/rules" \
  | jq 'del(.data.groups[]?.headers, .data.groups[]?.notifier_headers)'
```

Wrapped in `{"status":"success","data":{"groups":[...]}}`. Each group:

| Field | Meaning |
|---|---|
| `name` | group name from the YAML |
| `id`, `file` | group id to pass to `/api/v1/rule`, and the file it came from |
| `interval` | evaluation interval in seconds |
| `type` | `prometheus`, `vlogs` or `graphite` |
| `concurrency` | rules evaluated in parallel within the group |
| `lastEvaluation` | when the group last ran |
| `states` | count per state, e.g. `{"firing":1}` |
| `rules` | the rules below |

Each rule:

| Field | Meaning |
|---|---|
| `name` | alert or record name |
| `state` | `inactive`, `pending` or `firing` for an alerting rule. **Empty string for a recording rule** |
| `health` | `ok` or `err`. **Not** the same as `state` |
| `lastError` | evaluation error text, empty when healthy |
| `lastSamples` | samples the last evaluation returned. `0` means the expression matched nothing |
| `lastSeriesFetched` | series the datasource read. `0` means the selector matches nothing at all. Absent when the datasource does not report it |
| `type` | `alerting` or `recording` |
| `datasourceType` | `prometheus`, `vlogs` or `graphite` |
| `duration` | the `for` duration in seconds |
| `keep_firing_for` | in seconds |
| `evaluationTime` | how long the last evaluation took, in seconds |
| `id`, `group_id` | pass both to `/api/v1/rule` |
| `labels` | as written in the YAML plus the group's `labels` and `-external.label`, templates **not** rendered |
| `annotations` | as written in the YAML, templates **not** rendered |
| `alerts` | the active alerts, same shape as `/api/v1/alerts` |
| `debug` | whether `debug: true` is set. Always `false` for a recording rule |
| `max_updates_entries` | how many evaluations are retained, 20 by default |

`lastSamples` and `lastSeriesFetched` are the two fields that separate the common failures.
`fetched=0` is a selector which matches nothing, usually a misspelled metric name.
`fetched>0` with `samples=0` is a threshold which was never crossed.

## GET /api/v1/rule

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body \
  "$VM_ALERT_URL/api/v1/rule?group_id=$GROUP_ID&rule_id=$RULE_ID" | jq .
```

Both parameters are required. Unlike the other endpoints this one is **not** wrapped in
`{"status":...,"data":...}`: the rule fields are at the top level.

It returns every field from `/api/v1/rules` plus `updates`, the retained evaluation history,
newest first:

| Field in `updates[]` | Meaning |
|---|---|
| `time` | when vmalert ran the evaluation |
| `at` | the timestamp it evaluated *for*, which differs from `time` under `eval_delay` |
| `duration` | evaluation duration in nanoseconds |
| `samples` | samples returned by that evaluation |
| `series_fetched` | series read by that evaluation |
| `error` | `null` when fine and `{}` when the evaluation failed. The error text is only in `lastError` of `/api/v1/rules` |
| `curl` | **the exact request vmalert sent to the datasource**, fully encoded |

The `curl` field is empty for a failed evaluation.

## GET /api/v1/alerts

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body "$VM_ALERT_URL/api/v1/alerts" | jq .
```

Wrapped in `{"status":"success","data":{"alerts":[...]}}`.

| Field | Meaning |
|---|---|
| `name`, `state` | alert name, and `pending` or `firing` |
| `value` | the sample value which triggered it, as a string |
| `activeAt` | when the condition first became true, **not** when the alert fired. The alert fires `for` after this |
| `labels` | the rule's labels plus `alertname`, `alertgroup` and the series labels |
| `annotations` | **rendered**, so this is where a broken `dashboard` link shows up |
| `expression` | the expression text |
| `id`, `rule_id`, `group_id` | ids for `/api/v1/alert` |
| `source` | link to vmalert's own UI for this alert |
| `restored` | whether the state was restored from remote write on restart |
| `stabilizing` | whether `keep_firing_for` is holding it |

`alertgroup` is added automatically and its value is the group name, unless vmalert runs with
`-disableAlertgroupLabel`.

## GET /api/v1/alert

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body \
  "$VM_ALERT_URL/api/v1/alert?group_id=$GROUP_ID&alert_id=$ALERT_ID" | jq .
```

One alert, same fields as above. Both parameters are required.

## GET /api/v1/group

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body \
  "$VM_ALERT_URL/api/v1/group?group_id=$GROUP_ID" \
  | jq 'del(.headers, .notifier_headers)'
```

One group with its rules, same shape as one entry of `/api/v1/rules`.

## GET /api/v1/notifiers

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body "$VM_ALERT_URL/api/v1/notifiers" | jq .
```

```json
{"status":"success","data":{"notifiers":[
  {"kind":"static","targets":[{"address":"blackhole","labels":{},"lastError":""}]}]}}
```

`kind` is `static`, `consulSD` or `DNSSD` depending on discovery. A non-empty `lastError` on a target
means a firing alert is not reaching Alertmanager, which is a delivery fault rather than a rule
fault. An address of `blackhole` means vmalert runs with `-notifier.blackhole` and sends nothing
by design.

## POST /-/reload

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body -X POST "$VM_ALERT_URL/-/reload"
```

Sends vmalert a SIGHUP so it re-reads its rule files. Returns `200` with an empty body. It may be
protected by `-reloadAuthKey`: pass the key as the `authKey` query arg,
`"$VM_ALERT_URL/-/reload?authKey=..."`. A header gets `401`. This is the only write in this file.

## GET /flags

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body "$VM_ALERT_URL/flags"
```

Plain text, one flag per line, only the flags set on the command line. URLs and other secrets
show as `"secret"`:

```
-datasource.url="secret"
-notifier.blackhole="true"
-remoteRead.url="secret"
-remoteWrite.url="secret"
-rule="rules.yml"
-rule.evalDelay="5s"
```

A flag which is missing has its default value.

## ALERTS and ALERTS_FOR_STATE

With `-remoteWrite.url` set, vmalert writes two series per active alert on every evaluation,
timestamped with the evaluation time:

| Series | Value | Labels |
|---|---|---|
| `ALERTS` | `1` | the alert's labels, plus `alertstate="pending"` or `alertstate="firing"` |
| `ALERTS_FOR_STATE` | `activeAt`, as Unix seconds | the alert's labels |

The alert's labels include `alertname`, `alertgroup` (unless `-disableAlertgroupLabel`), the rule's
`labels` and the labels of the series the expression returned. When the alert leaves a state,
vmalert writes a stale marker, so the series ends at the last evaluation in that state. With
`-remoteRead.url` set, vmalert reads `ALERTS_FOR_STATE` once at startup to restore `activeAt`.

## Rule and group fields

Group level:

| Field | Purpose |
|---|---|
| `name` | required |
| `type` | `prometheus` (default), `vlogs` or `graphite` |
| `interval` | evaluation interval |
| `eval_offset` | pin evaluation to a fixed offset within the interval |
| `eval_delay` | shift the evaluated timestamp back, to let late data arrive. The fix when a rule misses an incident it clearly covers |
| `eval_alignment` | align the query timestamp to the interval; `true` by default |
| `limit` | cap the results of each rule in the group; above it the rule errors and drops all its results. Default `-rule.resultsLimit` |
| `concurrency` | rules evaluated in parallel |
| `labels` | added to every rule in the group, and outrank external labels |
| `params`, `headers` | extra query parameters and HTTP headers per datasource request. `/api/v1/rules` shows `headers` in plain text |
| `notifier_headers` | extra headers on notifications |
| `debug` | log the series count per evaluation and every state change |

Rule level:

| Field | Purpose |
|---|---|
| `record` | recording rule: the output metric name |
| `alert` | alerting rule: the alert name. Exactly one of `record` or `alert` |
| `expr` | required. MetricsQL, LogsQL or Graphite, per the group `type` |
| `for` | hold pending this long before firing |
| `keep_firing_for` | keep firing this long after the condition clears, which stops flapping |
| `annotations` | full templating, such as `{{ $value }}` and `{{ $labels.x }}` |
| `labels` | only `$labels`, `$value` and `$expr`. `$value` in a label makes a new alert on every change, so `for` never elapses |
| `debug` | as above, for the single rule |
| `update_entries_limit` | override how many evaluations are retained for this rule |
