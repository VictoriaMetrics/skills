---
name: victoriametrics-rules
description: >
  Write, check and debug vmalert alerting and recording rules for VictoriaMetrics and
  VictoriaLogs. Use when the user wants a new alerting or recording rule, asks whether or when a
  rule would fire over a past window, or asks why an alert fired, did not fire or fired late.
  Triggers on: alerting rule, recording rule, vmalert, alert did not fire, alert fired late,
  would this alert fire, for duration, keep_firing_for, LogsQL alert, vlogs rule.
allowed-tools: Bash(curl:*), Bash(jq:*), Bash(python3:*), Read
---

# vmalert rules

Everything here is an HTTP call against a running vmalert and its datasource. `/-/reload` is the
only write, and nothing writes to the datasource. Nothing needs the `vmalert` or `vmalert-tool`
binaries.

- Write a new rule: [Write a rule](#write-a-rule).
- Would a rule fire over a past window: [Check when a rule fires](#check-when-a-rule-fires).
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

- **Do not run `vmalert -replay` to answer "would this have fired".** Replay writes `ALERTS` and
  `ALERTS_FOR_STATE` to `-remoteWrite.url`, which injects synthetic alerts into production
  storage. `scripts/would_fire.py` answers the question and writes nothing.
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
   alert's labels in the URL. Labels accept only `$labels`, `$value` and `$expr`. Never put
   `$value` in a label: each new value makes a new alert, so `for` never elapses. `for` holds the
   alert until the condition has been true that long. `keep_firing_for` holds it after the
   condition clears, which stops a flapping alert.
3. **Check when it fires** against the window of a real past incident, with
   [Check when a rule fires](#check-when-a-rule-fires). Silence there means the rule would have
   missed that incident.
4. **Reload and verify.** Put the rule in a file that vmalert loads through `-rule`, then:

   ```bash
   curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body -X POST "$VM_ALERT_URL/-/reload"
   ```

   `/-/reload` answers 200 before it reads the files, also when one fails to parse. Check that
   `vmalert_config_last_reload_successful` in `$VM_ALERT_URL/metrics` is 1. If `-reloadAuthKey` is
   set, add `?authKey=<key>`; a header gets 401. `file` in `/api/v1/rules` shows where the loaded
   rule files are. Wait one interval, then [read the rule's state](#read-a-rules-state-now):
   `health=ok`, empty `lastError`, and `fetched` above zero. Before its first evaluation the rule
   shows `fetched=null`. Once it fires, check that the
   `dashboard` link in `/api/v1/alerts` opens the right panel.

## Check when a rule fires

`scripts/would_fire.py` sends what vmalert sends: one instant query per evaluation, at each
multiple of the interval, with vmalert's `step`. Then it applies `for` and `keep_firing_for` per
series. `<skill_base_dir>` is the directory that holds this SKILL.md. Run the script; there is no
need to read it.

Take the settings from vmalert, not from the rule file:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body "$VM_ALERT_URL/api/v1/rules" \
  | jq -r '.data.groups[] | .interval as $i | .params as $p | .eval_delay as $d | .rules[]
           | select(.name=="QueueBacklog")
           | "expr=\(.query)\tfor=\(.duration)s\tinterval=\($i)s\tkeep_firing_for=\(.keep_firing_for // 0)s\tparams=\($p // [])\teval_delay=\($d // "flag")\tgroup_id=\(.group_id)\tid=\(.id)"'
```

```bash
python3 <skill_base_dir>/scripts/would_fire.py \
  --url "$VM_METRICS_URL" \
  --query 'queue_depth{job="worker"} > 100' \
  --start 2026-09-30T15:12:00Z --end 2026-09-30T15:24:00Z \
  --step 30s --for 2m --keep-firing-for 0s --eval-step 300s
```

```
{job="worker"}
  pending 2026-09-30T15:15:30Z, fires 2026-09-30T15:17:30Z, resolved 2026-09-30T15:19:30Z
  pending 2026-09-30T15:20:30Z, never fires, cleared 2026-09-30T15:21:30Z before for=120s
```

- `--step` is the group `interval`. Another value moves every evaluation and gives wrong times.
- `--eval-step` is the `step=` in the rule's `curl` field (see
  [Read a rule's state now](#read-a-rules-state-now)), which is `-datasource.queryStep`, 5m by
  default. It decides how far back each query looks, so a range query with a short step can
  disagree with vmalert: `increase(x) > 12` covers 5m in vmalert's query and only 30s in a 30s
  range query.
- Pass each group param with `--param`, as `/api/v1/rules` lists it: `--param extra_label=env=dev`.
  Keep any params of `-datasource.url` in `--url`.
- Exit 0: a series is firing at some point inside the window, also when it fired before
  `--start`. Exit 1: none is. Exit 2: no verdict, because the datasource failed, returned a
  partial result, a warning or a reply the script cannot read, the query does not return an
  instant vector, or two series collide once `__name__` is dropped. Never report exit 2 as "the
  rule would not fire".
- The script reads the data as it is stored now, so it also sees data that arrived after vmalert
  evaluated it.
- With `keep_firing_for`, exit 1 is not proof: an alert can keep firing through short gaps from
  before the first evaluation checked. Check `ALERTS` for that window.
- It covers `type: prometheus` rules only. It does not send `-datasource.headers`, group `headers`
  or a tenant header, and does not apply `eval_offset`, `eval_delay`, `eval_alignment: false` or
  the group `limit`. Pass `-datasource.roundDigits` as `--param round_digits=N`. If one of these
  applies to the rule, say so with the verdict.

## Debug a past alert

Compare what vmalert decided, in `ALERTS` and `ALERTS_FOR_STATE`, with what the expression returns
over the same window.

### 1. Check that vmalert records its decisions

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body "$VM_ALERT_URL/flags" \
  | jq -Rr 'select(startswith("-remoteWrite.url") or startswith("-rule.evalDelay"))'
```

`/flags` lists only the flags set on the command line and hides URLs as `"secret"`. No
`-remoteWrite.url` line means vmalert kept no record: say that `-remoteWrite.url` stores the alert
state, and skip to step 3. The series usually land in `$VM_METRICS_URL`; if step 2 returns nothing
for an alert the user saw fire, ask where `-remoteWrite.url` points.

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

Run [Check when a rule fires](#check-when-a-rule-fires) over the same window. To see the values
themselves, run the expression without its comparison as a range query with `step` set to the
interval. Firing needs `for` / `interval` + 1 true evaluations in a row, and one evaluation with
no result restarts the count.

| Data | `ALERTS` | Cause |
|---|---|---|
| condition true | pending, then firing | The rule worked. If nobody was paged, read `references/notifier.md` |
| condition true | pending only | The condition cleared before `for` elapsed |
| condition true | no points | vmalert never saw it. If other series of the rule have points then, or `would_fire.py` says it fires, the data arrived late: raise `eval_delay` on the group or `-rule.evalDelay` (30s unless `/flags` lists it). With no points for any series, vmalert was down, the rule was failing, or evaluations were skipped (`vmalert_iteration_missed_total` in `/metrics`) |
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
   `fetched=null` means the datasource does not report the count.
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
- `type: graphite` rules: everything above applies except `would_fire.py`, because vmalert sends
  them to `/render`.
