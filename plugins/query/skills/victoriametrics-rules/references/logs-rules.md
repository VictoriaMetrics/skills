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

Leave the `_time:` filter out unless the rule needs a window other than the group interval.
Without one, vmalert queries the last group interval. A rule with its own `_time:` filter works,
but replay and range queries reject it with `range query is not supported for LogsQL expression
... because it contains time filter`.

When checking the expression yourself, send `start` and `end` as well as `time`, scoped to the
group interval, exactly as vmalert does. Without them the query counts every row in storage
rather than the interval, so a quiet window and a busy one return the same number:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body \
  --data-urlencode 'query=level:error | stats count() as errors' \
  --data-urlencode 'time=2026-09-22T01:30:00Z' \
  --data-urlencode 'start=2026-09-22T01:25:00Z' \
  --data-urlencode 'end=2026-09-22T01:30:00Z' \
  "$VM_LOGS_URL/select/logsql/stats_query" | jq '.data.result[].value[1]'
```

"Debug a past alert" and "Read a rule's state now" in SKILL.md apply to a `vlogs` rule. vmalert
writes its `ALERTS` to the `-remoteWrite.url` target, such as VictoriaMetrics, so query them on
`$VM_METRICS_URL`, never on `$VM_LOGS_URL`.

To check a `vlogs` rule on past logs, replay it as in "Check a rule" in SKILL.md, with
VictoriaLogs as the datasource. Unless the group sets `type: vlogs`, pass
`-rule.defaultRuleType=vlogs` to `-dryRun` too:

```bash
vmalert -rule=rules.yml \
  -datasource.url="$VM_LOGS_URL" \
  -rule.defaultRuleType=vlogs \
  -remoteWrite.url=http://localhost:18428 \
  -replay.timeFrom=2026-09-30T18:00:00Z -replay.timeTo=2026-09-30T19:00:00Z \
  -replay.disableProgressBar
```

`vmalert-tool unittest` takes only metric series as input, so it cannot test a `vlogs` rule.
