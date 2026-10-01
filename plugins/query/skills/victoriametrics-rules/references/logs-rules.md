# vlogs rules

A rule which queries VictoriaLogs sets `type: vlogs` on its group, and its `expr` is a LogsQL
stats query, because vmalert calls `/select/logsql/stats_query`.

```yaml
groups:
  - name: log-errors
    type: vlogs
    interval: 5m
    rules:
      - alert: ErrorSpike
        expr: 'level:error | stats count() as errors | filter errors:>50'
```

Put the threshold in the expression with a `filter` pipe. The rule fires on the rows the query
returns, so a bare `stats count()` always returns one row and always fires.

**Reference the count as `{{ $value }}`, never as `{{ $labels.<alias> }}`.** The stats alias does
not become a label of that name. vmalert renames it to `stats_result`, so a rule whose expression
says `stats by (app) count() as errorCount` produces the labels
`{alertname, alertgroup, app, stats_result="errorCount"}` and carries the count in the value.
Without `by (app)` there is no `app` label. An
annotation written as `{{ $labels.errorCount }}` renders empty, and nothing reports the mistake.
Use `{{ $labels.stats_result }}` if you want the alias name itself.

Write the expression without a `_time:` filter. vmalert supplies the time range from the group
interval when the query carries no time filter of its own. Add `_time:5m` and it stops, and a
range query then fails with `range query is not supported for LogsQL expression ... because it
contains time filter`.

When checking the expression yourself, send `start` and `end` as well as `time`, scoped to the
group interval, exactly as vmalert does. Without them the query counts every row in storage
rather than the interval, so a quiet window and a busy one return the same number:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  --data-urlencode 'query=level:error | stats count() as errors' \
  --data-urlencode 'time=2026-09-22T01:30:00Z' \
  --data-urlencode 'start=2026-09-22T01:25:00Z' \
  --data-urlencode 'end=2026-09-22T01:30:00Z' \
  "$VM_LOGS_URL/select/logsql/stats_query" | jq '.data.result[].value[1]'
```

Workflows A and B in SKILL.md apply to a `vlogs` rule. vmalert writes its `ALERTS` to the
`-remoteWrite.url` target, such as VictoriaMetrics, so query them on `$VM_METRICS_URL`, never on
`$VM_LOGS_URL`.

`would_fire.py` does not apply, because it queries the Prometheus API. For a past window, run the
rule's expression through `stats_query_range` with `step` set to the group interval, and a
`start` on a multiple of it. This example is a group with `interval: 30s`:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  --data-urlencode 'query=level:error | stats by (app) count() as errorCount | filter errorCount:>2' \
  --data-urlencode 'start=2026-09-30T18:06:00Z' \
  --data-urlencode 'end=2026-09-30T18:11:00Z' \
  --data-urlencode 'step=30s' \
  "$VM_LOGS_URL/select/logsql/stats_query_range" \
  | jq -r '.data.result[] | "\(.metric | del(.__name__) | tostring)\t\([.values[] | "\(.[0] | todate[11:19])=\(.[1])"] | join(" "))"'
```

```
{"app":"api"}	18:07:30=15 18:08:00=15 18:08:30=15 18:09:00=15
```

A value at `t` counts the logs in `[t, t+step)`, which is what vmalert's evaluation at
`t + interval` counts. Add one interval before you compare with `ALERTS`: this rule fired at
18:08:00, 18:08:30, 18:09:00 and 18:09:30. Apply `for` by hand: firing needs `for` / `interval` + 1
values in a row.
