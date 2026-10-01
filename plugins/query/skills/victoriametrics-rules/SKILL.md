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

Everything here is an HTTP call against a running vmalert and its datasource. Nothing needs the
`vmalert` or `vmalert-tool` binaries, and nothing writes to the datasource.

Pick the workflow by the question:

- An alert fired, did not fire, fired late or flapped in the past: Workflow A. vmalert's record
  of what it decided is the `ALERTS` and `ALERTS_FOR_STATE` series it writes to
  `-remoteWrite.url`.
- A rule is failing, quiet or firing now: Workflow B, then the checklist in "When a Rule Should
  Be Firing Now and Is Not".
- A new rule to write: read `references/writing-rules.md`.
- A rule with `type: vlogs`, or any LogsQL rule: read `references/logs-rules.md` before writing or
  checking it.
- A rule with `record:` instead of `alert:`: read `references/recording-rules.md`.
- A page that did not arrive, arrived twice, or resolved early: Workflow B step 5, then
  `references/notifier.md`.
- An endpoint field or parameter not shown here: read `references/api-reference.md`.

## Environment

```bash
# $VMALERT_URL   - the running vmalert, e.g. export VMALERT_URL="http://vmalert.example.com:8880"
#   through VictoriaMetrics with -vmalert.proxyURL: "http://localhost:8428/vmalert"
#   through cluster vmselect: "https://vmselect.example.com/select/0/prometheus/vmalert"
# $VM_METRICS_URL - the datasource vmalert queries, for checking an expression yourself
#   single: export VM_METRICS_URL="http://localhost:8428"
#   cluster: export VM_METRICS_URL="https://vmselect.example.com/select/0/prometheus"
# $VM_LOGS_URL    - VictoriaLogs base URL, for a vlogs rule
# $VM_ALERTMANAGER_URL - Alertmanager base URL, for references/notifier.md
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

- **Do not run `vmalert -replay` to answer "when would this have fired".** Replay writes its
  results to `-remoteWrite.url`, so against a real deployment it injects synthetic `ALERTS` and
  `ALERTS_FOR_STATE` into production storage. Workflow B step 4 answers the question and writes
  nothing.
- For a question about the past, read `ALERTS` and `ALERTS_FOR_STATE` first. vmalert keeps only
  the last 20 evaluations of a rule in memory (`-rule.updateEntriesLimit`), which at a 1m
  interval is 20 minutes, and debug mode is off by default.
- Read the rule's own evaluation history before theorising. `samples: 0` means the expression
  returned nothing, which is a different bug from a threshold never crossed.
- Check `health` and `lastError`, not only `state`. An evaluation error leaves `state` as it
  was, so a failing rule can show `inactive` or even `firing`.
- Never print the contents of `$VM_CURL_CONFIG`.

## Workflow A: Why Did an Alert Fire, Not Fire, or Fire Late

Use this for any window older than the rule's in-memory history. It reads what vmalert decided
and puts it next to what the data says. Copy this checklist and tick it off:

```
- [ ] 1. Rule settings, and -remoteWrite.url in /flags
- [ ] 2. ALERTS and ALERTS_FOR_STATE over the window
- [ ] 3. would_fire.py and the raw values over the same window
- [ ] 4. For each series: the `for` verdict, then what vmalert saw (table in step 3)
```

### 1. Read the rule and check that vmalert records its decisions

Take the rule's settings from vmalert, not from memory or the rule file:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/api/v1/rules" \
  | jq -r '.data.groups[] | .interval as $i | .eval_delay as $d | .rules[] | select(.name=="QueueBacklog")
           | "health=\(.health)\terr=\(.lastError)\texpr=\(.query)\tfor=\(.duration)s\tinterval=\($i)s\tkeep_firing_for=\(.keep_firing_for // 0)s\teval_delay=\(if $d then "\($d)s" else "flag" end)"'
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/flags" \
  | jq -Rr 'select(startswith("-remoteWrite.url") or startswith("-rule.evalDelay"))'
```

```
health=ok	err=	expr=queue_depth > 100	for=120s	interval=30s	keep_firing_for=0s	eval_delay=flag
-remoteWrite.url="secret"
-rule.evalDelay="5s"
```

`eval_delay=flag` means the group sets none, so `-rule.evalDelay` applies: the value in `/flags`,
or 30s when `/flags` does not list it. A group with `eval_offset` ignores both. The delay does not
move the timestamps: vmalert subtracts it from the clock and rounds down to a multiple of the
interval, so every query and `ALERTS` point still sits on the interval. It only decides how late
vmalert asks, which is what lets late data in.

`/flags` lists only the flags set on the command line and hides URLs as `"secret"`. No
`-remoteWrite.url` line means vmalert kept no record, so skip step 2. Tell the user that
`-remoteWrite.url` stores the alert state and `-remoteRead.url` restores it after a restart.

The line does not say where the series go. Query `$VM_METRICS_URL` first. If step 2 returns
nothing for a rule the user saw fire, ask where `-remoteWrite.url` points.

Behind vmauth, `/flags` and `/metrics` answer for vmauth itself: its flags start with
`-auth.config`. Through the `/vmalert` proxy of VictoriaMetrics they answer 400. In both cases,
read vmalert's flags from its scraped metrics instead, if something scrapes it:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  --data-urlencode 'query=flag{name=~"remoteWrite.url|rule.evalDelay|remoteRead.lookback"}' \
  "$VM_METRICS_URL/api/v1/query" \
  | jq -r '[.data.result[] | "\(.metric.instance)\t-\(.metric.name)=\(.metric.value)\tis_set=\(.metric.is_set)"] | sort[]'
```

```
127.0.0.1:8882	-remoteRead.lookback=1h0m0s	is_set=false
127.0.0.1:8882	-remoteWrite.url=secret	is_set=true
127.0.0.1:8882	-rule.evalDelay=5s	is_set=true
```

Every flag is there. `is_set=false` means the value shown is the default in effect. No result
means nothing scrapes vmalert into `$VM_METRICS_URL`. Then say that `-remoteWrite.url` cannot be
read, and take `ALERTS` series in step 2 as the proof that vmalert records its decisions.

### 2. Read what vmalert decided

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  --data-urlencode 'query=ALERTS{alertname="QueueBacklog"}' \
  --data-urlencode 'start=2026-09-30T15:12:00Z' \
  --data-urlencode 'end=2026-09-30T15:24:00Z' \
  --data-urlencode 'step=30s' \
  "$VM_METRICS_URL/api/v1/query_range" \
  | jq -r '.data.result[] | (.metric | del(.__name__, .alertname, .alertgroup, .alertstate) | tostring) as $l
           | "\($l)\t\(.metric.alertstate): \([.values[][0] | todate[5:19]] | join(" "))"'
```

```
{"job":"worker","severity":"warning"}	firing: 09-30T15:17:30 09-30T15:18:00 09-30T15:18:30 09-30T15:19:00
{"job":"worker","severity":"warning"}	pending: 09-30T15:15:30 09-30T15:16:00 09-30T15:16:30 09-30T15:17:00 09-30T15:20:30 09-30T15:21:00
```

While an alert is active, every evaluation writes one `ALERTS` sample with value `1`, the alert's
labels, and `alertstate` set to `pending` or `firing`. Set `step` to the group `interval` and
`start` to a multiple of it, so each point is one evaluation at the timestamp it evaluated for.
An unaligned `start` shifts every point and can drop one. End the window at least a minute in
the past, because the newest points are not complete yet.

One series can hold several episodes, as the `pending` line does here. `ALERTS_FOR_STATE`
separates them: its value is the episode's `activeAt`, so each distinct value is one episode. An
episode fired only if `ALERTS` has `firing` points inside it.

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  --data-urlencode 'query=ALERTS_FOR_STATE{alertname="QueueBacklog"}' \
  --data-urlencode 'start=2026-09-30T15:12:00Z' \
  --data-urlencode 'end=2026-09-30T15:24:00Z' \
  --data-urlencode 'step=30s' \
  "$VM_METRICS_URL/api/v1/query_range" \
  | jq -r '.data.result[] | (.metric | del(.__name__, .alertname, .alertgroup) | tostring) as $l
           | .values | map(.[1] | tonumber) | unique[] | "\($l)\tactiveAt=\(todate)"'
```

```
{"job":"worker","severity":"warning"}	activeAt=2026-09-30T15:15:30Z
{"job":"worker","severity":"warning"}	activeAt=2026-09-30T15:20:30Z
```

The rule has `for: 2m`. The first episode went pending at 15:15:30 and fired at 15:17:30. The
second went pending at 15:20:30 and cleared before `for` elapsed, so it never fired. An episode
resolves at the first evaluation after its last point, 15:19:30 for the first one here. With
`keep_firing_for`, the `firing` points go on for that long after the condition clears.

No line for a series means vmalert never had an active alert for it in the window. If step 3
shows the condition true for that series, vmalert never saw the data: read the third row of the
table.

### 3. Compare with what the data says

Run Workflow B step 4 over the same window, with `expr`, `for`, `interval` and `keep_firing_for`
from step 1 as `--query`, `--for`, `--step` and `--keep-firing-for`. It accepts them as printed. The
exit code covers all series, so add the user's labels to the selector, as in
`queue_depth{job="batch"} > 100`, when they ask about one:

```
{job="batch"}
  pending 2026-09-30T15:17:30Z, never fires, cleared 2026-09-30T15:19:30Z before for=120s
{job="worker"}
  pending 2026-09-30T15:15:30Z, fires 2026-09-30T15:17:30Z, resolved 2026-09-30T15:19:30Z
  pending 2026-09-30T15:20:30Z, never fires, cleared 2026-09-30T15:21:30Z before for=120s
```

For `job=worker` this matches step 2 exactly. For `job=batch` the data says pending, and step 2
has no point: vmalert never saw that data.

The script prints only when the condition held. To see how high the values went, run the
expression without its comparison:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  --data-urlencode 'query=queue_depth{job="batch"}' \
  --data-urlencode 'start=2026-09-30T15:16:00Z' \
  --data-urlencode 'end=2026-09-30T15:20:00Z' \
  --data-urlencode 'step=30s' \
  "$VM_METRICS_URL/api/v1/query_range" \
  | jq -r '.data.result[] | "\(.metric | del(.__name__) | tostring)\t\([.values[] | "\(.[0] | todate[11:19])=\(.[1])"] | join(" "))"'
```

```
{"job":"batch"}	15:16:00=20 15:16:30=20 15:17:00=20 15:17:30=300 15:18:00=300 15:18:30=300 15:19:00=300 15:19:30=20 15:20:00=20
```

vmalert sees one value per evaluation, while a dashboard draws every sample. A spike which looks
2 minutes long on the dashboard can hold for only 90 seconds of evaluations. To list the raw
samples, query a range selector at the end of the window:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  --data-urlencode 'query=queue_depth{job="batch"}[2m30s]' \
  --data-urlencode 'time=2026-09-30T15:19:20Z' \
  "$VM_METRICS_URL/api/v1/query" \
  | jq -r '.data.result[] | "\(.metric | del(.__name__) | tostring)\t\([.values[] | "\(.[0] | todate[11:19])=\(.[1])"] | join(" "))"'
```

```
{"job":"batch"}	15:16:58=20 15:17:08=20 15:17:18=20 15:17:28=300 15:17:38=300 15:17:48=300 15:17:58=300 15:18:08=300 15:18:18=300 15:18:28=300 15:18:38=300 15:18:48=300 15:18:58=300 15:19:08=300 15:19:18=300
```

Read the two side by side, one series at a time. Check the `for` verdict first: a run of N true
evaluations lasts N-1 intervals, so firing needs `for` / `interval` + 1 of them in a row. One
evaluation with no result restarts the count. A shorter run never fires, whatever vmalert saw.
`job=batch` above holds for 4 evaluations, 90 seconds, and needs 5, so it never fires for that
reason alone. A short run still goes pending, so it still writes `ALERTS` points. `job=batch` has
none, which is a second, separate finding.

| Data | `ALERTS` | Cause |
|---|---|---|
| condition true | pending, then firing at `activeAt` plus `for` | The rule worked. If nobody was paged, check delivery in Workflow B step 5 |
| condition true | pending only | The condition cleared before `for` elapsed, as in the 15:20:30 episode |
| condition true | no point at those times | vmalert never saw it: every evaluation where the condition held writes a pending or firing point. `job=batch` above has none. If step 2 shows points for other series of the same rule at those times, vmalert was running and the rule worked, so the data arrived after the evaluation; raise `eval_delay` on the group or `-rule.evalDelay` (30s unless `/flags` lists it). It should be at least the datasource's `-search.latencyOffset`, 30s by default. No API shows when a sample arrived, so this comparison is the evidence. With no points for any series, vmalert was down, the rule was failing, or evaluations ran longer than the interval and were skipped (`vmalert_iteration_missed_total` rising in `/metrics`) |
| condition false | no point | The threshold was never crossed |
| condition false | pending or firing | `keep_firing_for` held it, or the data changed after vmalert read it |

## Workflow B: What Is This Rule Doing Now

### 1. Find the rule and read its health

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/api/v1/rules" \
  | jq -r '.data.groups[].rules[]
           | "\(.name)\tstate=\(.state)\thealth=\(.health)\tsamples=\(.lastSamples)\tfetched=\(.lastSeriesFetched)\terr=\(.lastError)\tgroup_id=\(.group_id)\tid=\(.id)"'
```

```
E2EFlag	state=inactive	health=ok	samples=0	fetched=1	err=	group_id=6610928012533843372	id=8033498038201396685
```

`lastSamples` is how many samples the last evaluation returned, and `lastSeriesFetched` is how
many series the datasource read to produce them. `fetched=0` with `samples=0` means the selector
matches nothing. `vector(1)` or `absent(...)` fetch nothing and still return a sample, and `-1`
means the datasource does not report the count.

The command lists every rule. To find what is broken, scan it for `health=err` and `fetched=0`.
A rule over its `limit` shows `err=exec exceeded limit of N with M alerts` and `state=inactive`.
A recording rule has an empty `state`.

Step 2 takes `group_id` and `id` from this output.

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

vmalert keeps the last `max_updates_entries` evaluations per rule, 20 by default, set by
`-rule.updateEntriesLimit` or `update_entries_limit` on the rule. The history is in memory, so a
restart clears it. Each entry is one evaluation: `at` is the timestamp it evaluated for, and
`samples` is how many series the expression returned. A column of `samples=0` is the expression
returning nothing.

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

Run `scripts/would_fire.py`. It sends what vmalert sends: one instant query per evaluation, at each
multiple of `--step`, with `--eval-step` as the `step` parameter. Then it applies `for` per series,
`keep_firing_for` included. `<skill_base_dir>` is the directory holding this SKILL.md. Run the
script; there is no need to read it:

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

Take `--eval-step` from the `step=` in step 2's `curl` field. It is `-datasource.queryStep`, 5m by
default, and it decides how far back each query looks. A range query with a short `step` can
disagree with vmalert: `increase(x) > 12` written without a window covers 5m in vmalert's query and
fires, while a 30s range query covers far less and never fires. The script starts `for` twice early,
so an alert already pending at `--start` fires on time.

It exits 0 when a series fires inside the window, and 1 when none does. Exit 2 means there is no
verdict: the datasource was unreachable, rejected the query, or warned that a limit cut the result
short. Read the message, and never report exit 2 as "the rule would not fire". It stops after
1000 evaluations or 90 seconds; narrow the window if it does.

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

To check that the alerts reach Alertmanager, or to explain a duplicate or missing page, read
`references/notifier.md`.

## When a Rule Should Be Firing Now and Is Not

For a past window, use Workflow A. For a rule that is quiet now, work down this list.
Each step distinguishes two causes the previous one cannot.

1. `lastError` non-empty, or `health` not `ok`. The rule is failing, not quiet.
2. `fetched=0` and `samples=0` in Workflow B step 1. The selector matches nothing. Check the metric
   name and the label names against the datasource, for example with
   `count by (__name__) ({__name__=~"queue_dep.*"})`.
3. `samples=0` across the history in Workflow B step 2, with `fetched` above zero. The series
   exist and the threshold was never crossed. Run the `curl` from the update and look at the value.
4. `activeAt` set but no firing alert. The condition is true but `for` has not elapsed yet.
5. The condition is true in Workflow B step 4 but the rule never went pending. Suspect late
   data, and confirm it with Workflow A. `eval_delay` on the group shifts the evaluation
   back to compensate.
6. Still unexplained. Set `debug: true` on the group or the single rule and read vmalert's log.
   It records the series count per evaluation and every state change. Debug mode is off by
   default and logs only the evaluations after you turn it on, so it helps only when the problem
   happens again.

## Important Notes

- `/api/v1/rule` is the only endpoint here which is **not** wrapped in `{"status":...,"data":...}`; its fields sit at the top level
- `/api/v1/rule` and `/api/v1/alert` both require `group_id` **and** the rule or alert id, taken from `/api/v1/rules` or `/api/v1/alerts`
- `/-/reload` is the only write, and may be protected by `-reloadAuthKey`
- `type: graphite` rules take a Graphite render query as `expr`. Workflow B applies unchanged
