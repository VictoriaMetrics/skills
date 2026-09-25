# vmalert HTTP API reference

Every vmalert API path below is also served under a `/vmalert` prefix by default, so
`/api/v1/rules` and `/vmalert/api/v1/rules` are the same endpoint. The datasource paths, such as
`/api/v1/query_range`, are not. Use the bare form unless vmalert sits behind a
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
- [Rule and group fields](#rule-and-group-fields) - the YAML side
- [Datasource requests vmalert makes](#datasource-requests-vmalert-makes)

## GET /api/v1/rules

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/api/v1/rules" | jq .
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
| `health` | `ok`, `nodata` or `err`. **Not** the same as `state` |
| `lastError` | evaluation error text, empty when healthy |
| `lastSamples` | samples the last evaluation returned. `0` means the expression matched nothing |
| `lastSeriesFetched` | series the datasource read. `0` means the selector matches nothing at all |
| `type` | `alerting` or `recording` |
| `datasourceType` | `prometheus`, `vlogs` or `graphite` |
| `duration` | the `for` duration in seconds |
| `keep_firing_for` | in seconds |
| `evaluationTime` | how long the last evaluation took, in seconds |
| `id`, `group_id` | pass both to `/api/v1/rule` |
| `labels`, `annotations` | as written in the YAML, templates **not** rendered |
| `alerts` | the active alerts, same shape as `/api/v1/alerts` |
| `debug` | whether `debug: true` is set |
| `max_updates_entries` | how many evaluations are retained, 20 by default |

`lastSamples` and `lastSeriesFetched` are the two fields that separate the common failures.
`fetched=0` is a selector which matches nothing, usually a misspelled metric name.
`fetched>0` with `samples=0` is a threshold which was never crossed.

## GET /api/v1/rule

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VMALERT_URL/api/v1/rule?group_id=$GROUP_ID&rule_id=$RULE_ID" | jq .
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
| `error` | error for that evaluation, `null` when fine |
| `curl` | **the exact request vmalert sent to the datasource**, fully encoded |

The `curl` field is the most useful thing in this API. It removes any guesswork about which
timestamp, step and query text were used:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VMALERT_URL/api/v1/rule?group_id=$GROUP_ID&rule_id=$RULE_ID" | jq -r '.updates[0].curl'
```

## GET /api/v1/alerts

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/api/v1/alerts" | jq .
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

`alertgroup` is added automatically and its value is the group name.

## GET /api/v1/alert

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VMALERT_URL/api/v1/alert?group_id=$GROUP_ID&alert_id=$ALERT_ID" | jq .
```

One alert, same fields as above. Both parameters are required.

## GET /api/v1/group

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VMALERT_URL/api/v1/group?group_id=$GROUP_ID" | jq .
```

One group with its rules, same shape as one entry of `/api/v1/rules`.

## GET /api/v1/notifiers

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/api/v1/notifiers" | jq .
```

```json
{"status":"success","data":{"notifiers":[
  {"kind":"static","targets":[{"address":"blackhole","labels":{},"lastError":""}]}]}}
```

`kind` is `static`, `consul` or `dns` depending on discovery. A non-empty `lastError` on a target
means a firing alert is not reaching Alertmanager, which is a delivery fault rather than a rule
fault. An address of `blackhole` means vmalert runs with `-notifier.blackhole` and sends nothing
by design.

## POST /-/reload

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s -X POST "$VMALERT_URL/-/reload"
```

Sends vmalert a SIGHUP so it re-reads its rule files. Returns `200` with an empty body. It may be
protected by `-reloadAuthKey`, in which case pass the key. This is the only write in this file.

## Rule and group fields

Group level:

| Field | Purpose |
|---|---|
| `name` | required |
| `type` | `prometheus` (default), `vlogs` or `graphite` |
| `interval` | evaluation interval |
| `eval_offset` | pin evaluation to a fixed offset within the interval |
| `eval_delay` | shift the evaluated timestamp back, to let late data arrive. The fix when a rule misses an incident it clearly covers |
| `eval_alignment` | align the query timestamp to the interval |
| `limit` | cap the series a group may produce |
| `concurrency` | rules evaluated in parallel |
| `labels` | added to every rule in the group, and outrank external labels |
| `params`, `headers` | extra query parameters and HTTP headers per datasource request |
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
| `labels`, `annotations` | templated with `{{ $value }}` and `{{ $labels.x }}` |
| `debug` | as above, for the single rule |
| `update_entries_limit` | override how many evaluations are retained for this rule |

## Datasource requests vmalert makes

Knowing these lets you reproduce an evaluation exactly, which is what the `curl` field in
`/api/v1/rule` gives you for free.

| Group `type` | Instant query | Range query, used by replay |
|---|---|---|
| `prometheus` | `/api/v1/query` | `/api/v1/query_range` |
| `vlogs` | `/select/logsql/stats_query` | `/select/logsql/stats_query_range` |

For a `vlogs` rule whose expression carries **no** time filter, vmalert adds
`start = time - interval` and `end = time` to the instant query. When the expression carries its
own `_time:` filter it does not, and a range query is then refused with
`range query is not supported for LogsQL expression ... because it contains time filter`.

This is why a `vlogs` expression should be written without `_time:`, and why checking one by hand
needs `start` and `end` passed explicitly. Without them the query counts every row in storage
rather than the interval.

### How a vlogs stats result becomes labels and a value

`/select/logsql/stats_query` returns the stats alias as `__name__`:

```json
{"metric":{"__name__":"errorCount","app":"api"},"value":[1790193126,"36"]}
```

vmalert rewrites that `__name__` to a label called `stats_result` rather than dropping it, so a
firing alert from `level:error | stats by (app) count() as errorCount | filter errorCount:>10`
carries:

```json
{"value":"50",
 "labels":{"alertname":"ErrorSpike","alertgroup":"log-errors","app":"api","stats_result":"errorCount"}}
```

The count is the **value**. There is no label named `errorCount`, so `{{ $labels.errorCount }}`
renders empty. Use `{{ $value }}` for the count and `{{ $labels.stats_result }}` for the alias
name.

### Ingesting test logs into VictoriaLogs

`/insert/jsonline` requires `Content-Type: application/x-ndjson`. Without it VictoriaLogs answers
`200`, increments no drop counter, and stores nothing, which is indistinguishable from a
successful ingest until a later query comes back empty. `curl --data-binary` sends
`application/x-www-form-urlencoded` by default, so pass the header explicitly.
