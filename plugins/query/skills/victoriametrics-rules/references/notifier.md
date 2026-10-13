# Notifier: did the alert reach Alertmanager

To see whether vmalert is sending, read its own counters:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/metrics" \
  | jq -Rr 'select(test("^vmalert_alerts_(sent|send_errors)_total[{ ]"))'
```

```
vmalert_alerts_sent_total{addr="blackhole"} 1
vmalert_alerts_send_errors_total{addr="blackhole"} 0
```

One counter per notifier address. The counters count from vmalert's start, so read them twice and
compare. Behind vmauth, `/metrics` is vmauth's own, and the `/vmalert` proxy answers 400: query
`vmalert_alerts_sent_total` on `$VM_METRICS_URL` instead. When nothing scrapes vmalert, the counters
have no history and cannot prove delivery for a past window.

vmalert resends a firing alert at every evaluation (`-rule.resendDelay`, 0 by default), so
`sent_total` counts sends, not alerts. It rising with `send_errors_total` flat means the notifier
accepted the requests. `send_errors_total` rising means vmalert is trying and failing. Neither
proves the alert arrived: vmalert counts an alert before the `alert_relabel_configs` of a target
in `-notifier.config` drops it. Relabel rules can also change its labels, so the labels in
Alertmanager can differ from `ALERTS`.

Each send sets the alert's `endsAt` to four group intervals ahead, capped by
`-rule.maxResolveDuration`. If vmalert stops sending, Alertmanager resolves the alert on its own
after that time, even while vmalert still shows it firing.

These counters end at Alertmanager. Whether Alertmanager routed the alert to a person is its own
question; use the `alertmanager-query` skill for it.
`vmalert_alerts_send_duration_seconds` is the same set if you need latency.

## Duplicate pages and the way back to the rule

Alertmanager merges alerts with identical labels. Several vmalert replicas for high availability
must send identical labels, so a per-replica `-external.label` such as `replica=a` turns one alert
into one per replica, and each one pages. Alertmanager replicas must run as one cluster, and each
vmalert lists all of them in `-notifier.url`. Read the labels and the sender of each copy in
Alertmanager, and the flags of each vmalert:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VM_ALERTMANAGER_URL/api/v2/alerts" \
  | jq -r '.[] | select(.labels.alertname=="AMTDropped") | "\(.labels | tostring)\t\(.generatorURL)"'
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/flags" \
  | jq -Rr 'select(startswith("-external.") or startswith("-notifier.url"))'
```

```
{"alertgroup":"amt-drop","alertname":"AMTDropped","replica":"a","team":"nobody"}	http://vmalert-a:8880/vmalert/alert?group_id=3585880494480359597&alert_id=8872610984765735688
-external.label="replica=a"
-notifier.url="secret"
```

With `-external.alert.source` unset, `generatorURL` points to `vmalert/alert` on vmalert's
`-external.url`, so its host names the vmalert that sent the copy. `/flags` lists a flag only when
it is set. Pass the two ids to `/api/v1/alert` on that vmalert to get the rule:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  "$VMALERT_URL/api/v1/alert?group_id=3585880494480359597&alert_id=8872610984765735688" \
  | jq -r '"\(.name)\tstate=\(.state)\tgroup_id=\(.group_id)\trule_id=\(.rule_id)"'
```

```
AMTDropped	state=firing	group_id=3585880494480359597	rule_id=16544528060317955959
```

`group_id` and `rule_id` go to Workflow B step 2. The alert exists only while it is active; after
that, `/api/v1/alert` answers 404, and the `alertname` finds the rule in `/api/v1/rules`.

Alertmanager keeps no resolved alerts, and vmalert's counters have no per-alert history. For a
past page, only the receiver's own record, such as the channel, the pager or a webhook log, proves
what was delivered.
