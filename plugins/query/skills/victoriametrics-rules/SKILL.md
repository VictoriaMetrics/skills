---
name: victoriametrics-rules
description: >
  Inspect, debug and write vmalert alerting and recording rules against a running vmalert, for
  VictoriaMetrics and VictoriaLogs. Use this whenever the user mentions an alert that did not
  fire, fired late or fired too often, asks what a rule is doing, wants a new alerting or
  recording rule written, or asks when a rule would have fired over a past window, even if they
  do not say "vmalert" or "rule". Also use it before hand-writing any rule YAML or any curl
  against vmalert, because the live instance already holds the rule state, the last evaluations
  and the exact query it sent. Triggers on: alerting rule, recording rule, vmalert, alert did
  not fire, alert fired late, flapping alert, rule health, rule state, for duration,
  keep_firing_for, notifier, Alertmanager, LogsQL alert, vlogs rule, threshold, paging.
allowed-tools: Bash(curl:*), Bash(jq:*), Bash(python3:*), Read
---

# vmalert rules

Work against the running vmalert over HTTP. It already holds the rule state, the last
evaluations and the exact query it sent, so the answer to "why did this not fire" is usually one
GET away.

Everything here is an HTTP call against a deployment which is already running. Nothing in this
skill needs the `vmalert` or `vmalert-tool` binaries on the machine, and nothing writes to the
datasource.

## Environment

```bash
# $VMALERT_URL   - the running vmalert, e.g. export VMALERT_URL="http://vmalert.example.com:8880"
# $VM_METRICS_URL - the datasource vmalert queries, for checking an expression yourself
#   single: export VM_METRICS_URL="http://localhost:8428"
#   cluster: export VM_METRICS_URL="https://vmselect.example.com/select/0/prometheus"
# $VM_LOGS_URL    - VictoriaLogs base URL, for a vlogs rule
# $VM_CURL_CONFIG - curl config file with an auth header. Leave unset for a local instance.
```

## Auth Pattern

Every command loads auth from a curl config file, which works for both remote and local:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/api/v1/rules" | jq .
```

When `VM_CURL_CONFIG` is unset, curl reads `/dev/null` and sends no auth header. When set, it must
point to a mode-0600 curl config file containing `header = "Authorization: Bearer <token>"`. Never
print its contents.

`scripts/would_fire.py` calls curl the same way, so it reads the same file and needs no token on
its command line.

## Critical Rules

- **Do not reach for `vmalert -replay` to answer "when would this have fired".** Replay exists
  to backfill: it evaluates rules over a past window and writes the results to
  `-remoteWrite.url`, which is how you give a newly added recording rule some history. That
  write is the point of it, so against a real deployment it also injects synthetic `ALERTS` and
  `ALERTS_FOR_STATE` into production storage. Step 4 answers the "would it have fired" question
  with a range query and writes nothing.
- Read the rule's own evaluation history before theorising. `samples: 0` means the expression
  returned nothing, which is a different bug from a threshold never crossed.
- Check `health` and `lastError`, not only `state`. A rule failing at evaluation reports
  `state: inactive`, which looks like a quiet rule.
- Never print the contents of `$VM_CURL_CONFIG`.

## Workflow: What Is This Rule Doing

### 1. Find the rule and read its health

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/api/v1/rules" \
  | jq -r '.data.groups[].rules[]
           | "\(.name)\tstate=\(.state)\thealth=\(.health)\tsamples=\(.lastSamples)\tfetched=\(.lastSeriesFetched)\terr=\(.lastError)"'
```

```
VMUptimeHigh	state=firing	health=ok	samples=1	fetched=1	err=
```

`lastSamples` is how many samples the last evaluation returned, and `lastSeriesFetched` is how
many series the datasource read to produce them. `fetched=0` means the selector matches nothing,
so the rule can never fire whatever the threshold is.

Keep the `id` and `group_id` from this response for step 2.

### 2. Read the per-evaluation history

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VMALERT_URL/api/v1/rule?group_id=$GROUP_ID&rule_id=$RULE_ID" \
  | jq -r '.updates[] | "\(.at)\tsamples=\(.samples)\tfetched=\(.series_fetched)\terr=\(.error)"'
```

```
2026-09-25T02:49:50+05:30	samples=1	fetched=1	err=null
2026-09-25T02:49:45+05:30	samples=1	fetched=1	err=null
```

vmalert keeps the last `max_updates_entries` evaluations per rule, 20 by default. Each entry is
one evaluation: `at` is the timestamp it evaluated for, and `samples` is how many series the
expression returned. A column of `samples=0` is the expression returning nothing.

Each entry also carries a `curl` field holding the exact request vmalert sent to the datasource,
query encoding, `time` and `step` included:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VMALERT_URL/api/v1/rule?group_id=$GROUP_ID&rule_id=$RULE_ID" | jq -r '.updates[0].curl'
```

Run that command to see what vmalert saw. It settles most disagreements about a rule, because it
removes the guesswork about which timestamp and step were used.

### 3. Read the firing alert and its rendered annotations

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/api/v1/alerts" \
  | jq -r '.data.alerts[] | "\(.name)\t\(.state)\tvalue=\(.value)\tactiveAt=\(.activeAt)"'
```

```
VMUptimeHigh	firing	value=45	activeAt=2026-09-25T02:49:15+05:30
```

`activeAt` is when the condition first became true, not when the alert fired. With `for: 5m` the
alert fires `for` after `activeAt`. The annotations in this response are rendered, so this is
where a broken `dashboard` link or an empty `summary` shows up.

### 4. Work out when a rule fires over a past window, read-only

Run the whole alerting expression, comparison included, as a range query. A filtering comparison
drops the samples where it is false, so every returned point is a moment the condition held:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  --data-urlencode 'query=sum(rate(http_requests_total{code=~"5.."}[5m])) by (job) / sum(rate(http_requests_total[5m])) by (job) > 0.05' \
  --data-urlencode 'start=2026-09-22T00:00:00Z' \
  --data-urlencode 'end=2026-09-22T02:00:00Z' \
  --data-urlencode 'step=1m' \
  "$VM_METRICS_URL/api/v1/query_range" | jq '.data.result[].values | length'
```

`<skill_base_dir>/scripts/would_fire.py` does that query and applies the `for` duration for you:

```bash
python3 <skill_base_dir>/scripts/would_fire.py \
  --url "$VM_METRICS_URL" \
  --query 'sum(rate(http_requests_total{code=~"5.."}[5m])) by (job) / sum(rate(http_requests_total[5m])) by (job) > 0.05' \
  --start 2026-09-22T00:00:00Z --end 2026-09-22T02:00:00Z \
  --step 1m --for 5m
```

```
job=api
  condition true at 58 of 58 steps, first 2026-09-22T01:03:00+00:00, last 2026-09-22T02:00:00+00:00
  fires 2026-09-22T01:08:00+00:00 (pending from 2026-09-22T01:03:00+00:00, for=300s)
```

It exits 1 when no series has an unbroken run that reaches the `for` duration, and 0 when at least
one series fires, so it works in a check. Exit 2 means the check could not run, for example the
datasource was unreachable or rejected the query: read the message, and never report exit 2 as
"the rule would not fire". `for` and `--step` accept vmalert durations such as
`1h30m` or `500ms`. A `WARNING from the datasource` line means a query limit cut the result
short: narrow the window or raise the limit before you trust the verdict. The request gives up
after 90 seconds with an error.

The `for` arithmetic is the reason this is a script rather than four lines inline. A run of N
points spans only N-1 steps, so counting points instead of measuring elapsed time from the start
of the run reports the fire time one step early. A gap has to restart the pending clock, because
a missing point means the condition was false then.

This gives the same answer as replay and writes nothing. On the window above, replay also
reports 01:08.

### 5. Confirm the alert has somewhere to go

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/api/v1/notifiers" \
  | jq -r '.data.notifiers[] | .kind as $k | .targets[] | "\($k)\t\(.address)\terr=\(.lastError)"'
```

```
static	blackhole	err=
```

A firing rule with a notifier `lastError` is a delivery problem, not a rule problem. An address
of `blackhole` means `-notifier.blackhole` is set and nothing is being sent by design.

To confirm notifications are actually leaving vmalert, read its own counters:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/metrics" \
  | jq -Rr 'select(test("^vmalert_alerts_(sent|send_errors)_total[{ ]"))'
```

```
vmalert_alerts_sent_total{addr="blackhole"} 1
vmalert_alerts_send_errors_total{addr="blackhole"} 0
```

One counter per notifier address. `sent_total` rising while an alert fires is proof the
notification path works end to end. `sent_total` flat with a firing alert means nothing is being
delivered, and `send_errors_total` rising tells you vmalert is trying and failing.
`vmalert_alerts_send_duration_seconds` is the same set if you need latency.

## Workflow: Writing a New Rule

### 1. Run the expression before writing the rule around it

Use the `victoriametrics-query` skill for MetricsQL, or `victorialogs-query` for LogsQL. An
expression which returns nothing produces a rule which never fires, and no later check reports
that as an error.

### 2. Write the rule

```yaml
groups:
  - name: api-availability
    interval: 1m
    rules:
      - record: job:http_requests:rate5m
        expr: sum(rate(http_requests_total[5m])) by (job)

      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{code=~"5.."}[5m])) by (job)
            / sum(rate(http_requests_total[5m])) by (job) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "{{ $labels.job }} serves {{ $value | humanizePercentage }} 5xx"
          dashboard: "https://grafana.example.com/d/abc123/api?var-job={{ $labels.job }}"
```

Give every alert a `dashboard` annotation which opens the panel showing the same series, with
the alert's own labels templated into the URL. The person woken at 03:00 starts there. Step 3 of
the first workflow shows the rendered link, so check it resolves before trusting it.

`for` holds the alert until the condition has been true that long. `keep_firing_for` holds it
after the condition clears, which stops a flapping alert from resolving and re-firing.

### 3. Check when it would fire

Use step 4 above against the window of a real past incident. Silence there means the rule would
have missed it.

### 4. Deploy, reload, then verify against the live instance

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s -X POST "$VMALERT_URL/-/reload"
```

`/-/reload` sends vmalert a SIGHUP to re-read its rule files. It may be protected by
`-reloadAuthKey`. Then run steps 1 and 2 of the first workflow and confirm `health=ok`,
`lastError` empty, and `fetched` greater than zero.

## Logs Rules

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
says `count() as errorCount` produces the labels
`{alertname, alertgroup, app, stats_result="errorCount"}` and carries the count in the value. An
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

Everything in the first workflow applies to a `vlogs` rule unchanged. `/api/v1/rules` reports
`datasourceType: vlogs` for it, and `would_fire.py` does not: it queries the Prometheus
range API, so use the `stats_query` call above for a logs rule instead.

## Recording Rules

A recording rule precomputes an expression and writes the result back under a new metric name, so
it has no threshold, no `for`, and no alert. Its shape in `/api/v1/rules` differs from an alerting
rule in ways that look like faults if you expect the alerting fields:

| Field | Recording rule |
|---|---|
| `state` | **empty string**, not `inactive`. There is nothing to fire |
| `type` | `recording` |
| `lastSamples` | the number of output series it produced. This is the health signal |

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/api/v1/rules" \
  | jq -r '.data.groups[].rules[] | select(.type=="recording")
           | "\(.name)\thealth=\(.health)\tsamples=\(.lastSamples)\terr=\(.lastError)"'
```

Verify it by querying the output metric on the datasource, not by looking for an alert:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  --data-urlencode 'query=job:http_requests:rate5m' \
  "$VM_METRICS_URL/api/v1/query" | jq '.data.result'
```

An empty result with `lastSamples` above zero means vmalert computed the series but they are not
reaching storage, which is a remote write problem. Name recording rules
`level:metric:operation`, as in `job:http_requests:rate5m`, so the output name says what it
aggregates.

Two things that differ from alerting rules:

- vmalert refuses to start when the config holds any recording rule and `-remoteWrite.url` is
  unset, with `config contains recording rules but -remoteWrite.url isn't set`. There is nowhere
  to put the output otherwise.
- `would_fire.py` does not apply. It needs a comparison in the expression to find the points
  where a condition held, and a recording rule has none.

## When a Rule Should Have Fired and Did Not

Work down this list. Each step distinguishes two causes the previous one cannot.

1. `lastError` non-empty, or `health` not `ok`. The rule is failing, not quiet.
2. `fetched=0` in step 1. The selector matches nothing. Check label names against the datasource.
3. `samples=0` across the history in step 2, with `fetched` above zero. The series exist and the
   threshold was never crossed. Run the `curl` from the update and look at the value.
4. `activeAt` set but no firing alert. The condition is true but `for` has not elapsed yet.
5. The condition was true in step 4's range query but the live rule never saw it. Suspect
   ingestion delay: the rule evaluates a timestamp whose data had not arrived. `eval_delay` on
   the group shifts the evaluation back to compensate.
6. Still unexplained. Set `debug: true` on the group or the single rule and read vmalert's log.
   It records the series count per evaluation and every state change.

## A Third Rule Type

`type` accepts `graphite` as well as `prometheus` and `vlogs`. A graphite rule's `expr` is a
Graphite render query, and an unrecognised value fails with
`unknown datasource type=%q, want prometheus, graphite or vlogs`. Everything in the first
workflow applies to it unchanged.

## Important Notes

- `/api/v1/rule` is the only endpoint here which is **not** wrapped in `{"status":...,"data":...}`; its fields sit at the top level
- `/api/v1/rule` and `/api/v1/alert` both require `group_id` **and** the rule or alert id, taken from `/api/v1/rules`
- `health` and `state` are different fields. A rule failing at evaluation reports `state: inactive`, which looks like a quiet rule
- Annotations are rendered in `/api/v1/alerts` but raw in `/api/v1/rules`, so check the rendered form when a `dashboard` link looks wrong
- Every path is also served under a `/vmalert` prefix
- `/-/reload` is the only write, and may be protected by `-reloadAuthKey`
- For full endpoint details, parameters, and response formats, see `references/api-reference.md`
