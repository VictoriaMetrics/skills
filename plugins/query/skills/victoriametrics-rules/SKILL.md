---
name: victoriametrics-rules
description: >
  Write, check and debug vmalert alerting and recording rules for VictoriaMetrics and
  VictoriaLogs. Use when the user wants a new alerting or recording rule, asks whether or when a
  rule would fire over a past window, or asks why an alert fired, did not fire or fired late.
  Triggers on: alerting rule, recording rule, vmalert, alert did not fire, alert fired late,
  would this alert fire, for duration, keep_firing_for, LogsQL alert, vlogs rule.
allowed-tools: Bash(curl:*), Bash(jq:*), Bash(vmalert:*), Bash(vmalert-tool:*), Read
---

# vmalert rules

Most steps are HTTP calls against a running vmalert and its datasource, and `/-/reload` is the
only write to it. Checking a rule uses the `vmalert` and `vmalert-tool` binaries, and replay
writes only to a scratch VictoriaMetrics.

- Write a new rule: [Write a rule](#write-a-rule).
- Is a rule valid, and would it fire: [Check a rule](#check-a-rule).
- Why an alert fired, did not fire or fired late: [Debug a past alert](#debug-a-past-alert).
- A rule that fails or stays quiet now: [Read a rule's state now](#read-a-rules-state-now).
- A `type: vlogs` rule: also read `references/logs-rules.md`.
- A `record:` rule: also read `references/recording-rules.md`.
- A page that did not arrive, arrived twice or resolved early: `references/notifier.md`.
- A field or endpoint not shown here: `references/api-reference.md`.

## Environment

```bash
# $VM_ALERT_URL   - the running vmalert, e.g. export VM_ALERT_URL="http://vmalert.example.com:8880"
#   through VictoriaMetrics with -vmalert.proxyURL: "http://localhost:8428/vmalert"
#   through cluster vmselect: "https://vmselect.example.com/select/0/prometheus/vmalert"
# $VM_METRICS_URL - the datasource vmalert queries, and where its ALERTS series are stored
#   single: export VM_METRICS_URL="http://localhost:8428"
#   cluster: export VM_METRICS_URL="https://vmselect.example.com/select/0/prometheus"
# $VM_LOGS_URL    - VictoriaLogs base URL, for a vlogs rule
# $VM_CURL_CONFIG - curl config file with an auth header. Leave unset for a local instance.
```

Log rules often run on a separate vmalert. Point `$VM_ALERT_URL` at the vmalert that runs the rule.

`$VM_METRICS_URL/api/v1/alerts`, which other skills read, is the same vmalert through
`-vmalert.proxyURL`. That proxy does not serve `/flags`, `/metrics` or `/-/reload`, so point
`$VM_ALERT_URL` at vmalert itself when a step needs them.

## Auth Pattern

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body "$VM_ALERT_URL/api/v1/rules" \
  | jq 'del(.data.groups[]?.headers, .data.groups[]?.notifier_headers)'
```

When `VM_CURL_CONFIG` is unset, curl reads `/dev/null` and sends no auth header. When set, it must
point to a mode-0600 curl config file containing `header = "Authorization: Bearer <token>"`. Never
print its contents. `/api/v1/rules` lists the group `headers` in plain text, so drop them as
above. If vmalert and its datasource need different credentials, ask the user which file to use
for each.

## Critical Rules

- **Replay into a scratch VictoriaMetrics, never into production.** `vmalert -replay` writes
  `ALERTS` and `ALERTS_FOR_STATE` to `-remoteWrite.url`.
- For an alert in the past, start from `ALERTS` and `ALERTS_FOR_STATE`. vmalert keeps only the
  last 20 evaluations of a rule in memory (`-rule.updateEntriesLimit`), a restart clears them, and
  debug mode is off by default.
- Check `health` and `lastError`, not only `state`. An evaluation error leaves `state` as it was,
  so a failing rule can show `inactive` or `firing`.

## Write a rule

1. **Run the expression first** with the `victoriametrics-query` skill, or `victorialogs-query`
   for LogsQL. An expression that returns nothing makes a rule that never fires, and nothing
   reports it as an error.
2. **Write the rule.** Put the threshold in the expression, so the rule fires on the series it
   returns:

   ```yaml
   groups:
     - name: api-availability
       interval: 1m
       rules:
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

   Give every alert a `dashboard` annotation that opens the panel for the same series, with the
   alert's labels in the URL. Labels of an alerting rule accept only `$labels`, `$value` and
   `$expr`. Never put `$value` in a label: each new value makes a new alert, so `for` never
   elapses. `for` holds the alert until the condition has been true that long. `keep_firing_for`
   holds it after the condition clears, which stops a flapping alert.
3. **Check it** with [Check a rule](#check-a-rule): validate it, unit-test it, and replay it over a
   real past incident. Silence in the replay means the rule would have missed that incident.
4. **Reload and verify.** Put the rule in a file that vmalert loads through `-rule`, then:

   ```bash
   curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body -X POST "$VM_ALERT_URL/-/reload"
   ```

   `/-/reload` answers 200 before it reads the files, also when one fails to parse. Check that
   `vmalert_config_last_reload_successful` in `$VM_ALERT_URL/metrics` is 1. If `-reloadAuthKey` is
   set, add `?authKey=<key>`; a header gets 401. `file` in `/api/v1/rules` shows where the loaded
   rule files are. Wait one interval, then [read the rule's state](#read-a-rules-state-now):
   `health=ok`, empty `lastError`, and `fetched` above zero. `fetched=null` is normal before the
   first evaluation and for `type: vlogs` rules. Once it fires, check that the
   `dashboard` link in `/api/v1/alerts` opens the right panel.

## Check a rule

1. **Validate** the file. vmalert parses the expressions and templates and needs no datasource:

   ```bash
   vmalert -rule=rules.yml -dryRun
   ```

   Exit code 0 means the file is valid.

2. **Unit-test** it on made-up series. A test says when the alert fires, with which labels and
   annotations, and covers `for` and `keep_firing_for`. See `references/unittest.md`:

   ```bash
   vmalert-tool unittest --files=rules_test.yml
   ```

3. **Replay** it on real data to see whether it would have fired in a past incident. Ask the
   user for a scratch VictoriaMetrics, such as one they start with
   `docker run -d --rm -p 18428:8428 victoriametrics/victoria-metrics`. Point `-remoteWrite.url`
   at it, never at production or `$VM_METRICS_URL`. Pass the same `-datasource.*` auth flags and
   `-external.label` as the running vmalert; `$VM_ALERT_URL/flags` lists them:

   ```bash
   vmalert -rule=rules.yml \
     -datasource.url="$VM_METRICS_URL" \
     -remoteWrite.url=http://localhost:18428 \
     -replay.timeFrom=2026-09-30T15:00:00Z -replay.timeTo=2026-09-30T16:00:00Z \
     -replay.disableProgressBar
   ```

   Then read `ALERTS` as in [Read what vmalert decided](#2-read-what-vmalert-decided), with the
   scratch URL in place of `$VM_METRICS_URL`. New series take a few seconds to
   become searchable, so an empty answer right after replay is not a miss: query again. Replay
   sends no notifications. It ignores `keep_firing_for` and the group `limit`, disables the
   `query` template function, and does not run `type: graphite` rules. It sends range queries
   with `step` set to the group interval and no `eval_delay`, on the data as stored now, so it
   can differ from what vmalert saw live.

## Debug a past alert

Compare what vmalert decided, in `ALERTS` and `ALERTS_FOR_STATE`, with what the expression returns
over the same window.

### 1. Check that vmalert records its decisions

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body "$VM_ALERT_URL/flags" \
  | jq -Rr 'select(startswith("-remoteWrite.url") or startswith("-rule.evalDelay"))'
```

`/flags` lists only the flags set on the command line and hides URLs as `"secret"`. If vmalert
runs with `-flagsAuthKey`, add `?authKey=<key>`: without it `/flags` answers 401 and the filter
above prints nothing. No `-remoteWrite.url` line means vmalert kept no record: say that
`-remoteWrite.url` stores the alert state, and skip to step 3. The series usually land in
`$VM_METRICS_URL`; if step 2 returns nothing for an alert the user saw fire, ask where
`-remoteWrite.url` points.

### 2. Read what vmalert decided

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body \
  --data-urlencode 'query=ALERTS{alertname="QueueBacklog"}' \
  --data-urlencode 'start=2026-09-30T15:12:00Z' \
  --data-urlencode 'end=2026-09-30T15:24:00Z' \
  --data-urlencode 'step=30s' \
  "$VM_METRICS_URL/api/v1/query_range" \
  | jq -r '.data.result[] | (.metric | del(.__name__, .alertname, .alertgroup, .alertstate) | tostring) as $l
           | "\($l)\t\(.metric.alertstate): \([.values[][0] | todate[11:19]] | join(" "))"'
```

```
{"job":"worker"}	firing: 15:17:30 15:18:00 15:18:30 15:19:00
{"job":"worker"}	pending: 15:15:30 15:16:00 15:16:30 15:17:00 15:20:30 15:21:00
```

Each evaluation of an active alert writes one `ALERTS` point with `alertstate` `pending` or
`firing`. Set `step` to the group interval and `start` to a multiple of it, so each point is one
evaluation. One series can hold several episodes. `ALERTS_FOR_STATE` separates them: its value is
the episode's `activeAt`, so each distinct value is one episode:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body \
  --data-urlencode 'query=ALERTS_FOR_STATE{alertname="QueueBacklog"}' \
  --data-urlencode 'start=2026-09-30T15:12:00Z' \
  --data-urlencode 'end=2026-09-30T15:24:00Z' \
  --data-urlencode 'step=30s' \
  "$VM_METRICS_URL/api/v1/query_range" \
  | jq -r '.data.result[] | (.metric | del(.__name__, .alertname, .alertgroup) | tostring) as $l
           | .values | map(.[1] | tonumber) | unique[] | "\($l)\tactiveAt=\(todate)"'
```

`activeAt` is when the condition became true, not when the alert fired. An episode resolved at
the first evaluation after its last point. An alert that vmalert
restores from `ALERTS_FOR_STATE` after a restart can go straight to firing, with no pending points.

### 3. Compare with the data

Replay the rule over the same window, as in [Check a rule](#check-a-rule). To see the values
themselves, run the expression without its comparison as a range query with `step` set to the
interval. Firing needs `for` / `interval` + 1 true evaluations in a row, and one evaluation with
no result restarts the count.

| Data | `ALERTS` | Cause |
|---|---|---|
| condition true | pending, then firing | The rule worked. If nobody was paged, read `references/notifier.md` |
| condition true | pending only | The condition cleared before `for` elapsed |
| condition true | no points | vmalert never saw it. If other series of the rule have points then, or a replay fires, the data arrived late: raise `eval_delay` on the group or `-rule.evalDelay` (30s unless `/flags` lists it). With no points for any series, vmalert was down, the rule was failing, or evaluations were skipped (`vmalert_iteration_missed_total` in `/metrics`) |
| condition false | no points | The threshold was never crossed |
| condition false | pending or firing | `keep_firing_for` held it, or the data changed after vmalert read it |

## Read a rule's state now

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body "$VM_ALERT_URL/api/v1/rules" \
  | jq -r '.data.groups[].rules[]
           | "\(.name)\tstate=\(.state)\thealth=\(.health)\tsamples=\(.lastSamples)\tfetched=\(.lastSeriesFetched)\terr=\(.lastError)\tgroup_id=\(.group_id)\tid=\(.id)"'
```

```
E2EFlag	state=inactive	health=ok	samples=0	fetched=1	err=	group_id=6610928012533843372	id=8033498038201396685
```

Work down this list:

1. `health=err` or a `lastError`: the rule is failing, not quiet. Over its `limit`, it shows
   `exec exceeded limit of N with M alerts`. A `400` from the datasource can come from a group
   param such as `extra_filters`; read the group's `params` in `/api/v1/rules`.
2. `fetched=0` and `samples=0`: the selector matches nothing. Check the metric and label names,
   for example with `count by (__name__) ({__name__=~"queue_dep.*"})` on `$VM_METRICS_URL`.
   `fetched=null` means the datasource does not report the count, as VictoriaLogs never does.
3. `samples=0` with `fetched` above zero: the series exist and the threshold is not crossed.
4. `state=pending`: the condition is true and `for` has not elapsed yet.

The rule's last evaluations, newest first, and the exact request vmalert sent for the newest one:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body \
  "$VM_ALERT_URL/api/v1/rule?group_id=$GROUP_ID&rule_id=$RULE_ID" \
  | jq -r '(.updates[] | "\(.at)\tsamples=\(.samples)\tfetched=\(.series_fetched)\tfailed=\(.error != null)"), .updates[0].curl'
```

Run the `curl` command to see what vmalert saw. Its URL is the datasource as vmalert reaches it;
change the host if that name does not resolve where you run it. vmalert hides credentials in it
unless it runs with `-datasource.showURL`: a header with `auth`, `pass`, `key`, `secret` or `token`
in its name shows as `<secret>`, and a password in the URL as `xxxxx`. Replace the `<secret>` header
with `--config "$VM_CURL_CONFIG"`. vmalert adds `-k` for every https datasource; drop it unless
vmalert runs with `-datasource.tlsInsecureSkipVerify`. Other headers, such as `Cookie`, are not
hidden, so check them before you share the output. The field is empty for a failed evaluation; read
`lastError` then.

If the cause is still unclear, set `debug: true` on the rule and read vmalert's log. It logs only
the evaluations after you turn it on.

## Important Notes

- `/api/v1/rule`, `/api/v1/alert` and `/api/v1/group` are **not** wrapped in
  `{"status":...,"data":...}`. `/api/v1/rule` and `/api/v1/alert` need `group_id` and the rule or
  alert id.
- `type: graphite` rules: everything above applies except replay.
