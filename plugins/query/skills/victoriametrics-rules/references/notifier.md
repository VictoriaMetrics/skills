# Notifier: did the alert reach Alertmanager

To see whether vmalert is sending, read its own counters:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body "$VM_ALERT_URL/metrics" \
  | jq -Rr 'select(test("^vmalert_alerts_(sent|send_errors)_total[{ ]"))'
```

```
vmalert_alerts_sent_total{addr="blackhole"} 1
vmalert_alerts_send_errors_total{addr="blackhole"} 0
```

One counter per notifier address, for the sends of all rules, so it cannot show which alert was
sent. The counters count from vmalert's start, so read them twice and compare. If
`$VM_ALERT_URL/metrics` is not vmalert's own (behind vmauth or the `/vmalert` proxy), query
`vmalert_alerts_sent_total` on `$VM_METRICS_URL` instead. When nothing scrapes vmalert, the counters
have no history and cannot prove delivery for a past window.

vmalert resends a firing alert at every evaluation (`-rule.resendDelay`, 0 by default), so
`sent_total` counts sends, not alerts. It rising with `send_errors_total` flat means the notifier
accepted the requests. `send_errors_total` rising means vmalert is trying and failing. Neither
proves the alert arrived: vmalert counts an alert before the `alert_relabel_configs` of a target
in `-notifier.config` drops it. The top-level `alert_relabel_configs` in that file runs first, and
an alert it drops is never counted. Relabel rules can also change its labels, so the labels in
Alertmanager can differ from `ALERTS`.

Each send sets the alert's `endsAt` to four group intervals ahead, capped by
`-rule.maxResolveDuration`. If vmalert stops sending, Alertmanager resolves the alert on its own
after that time, even while vmalert still shows it firing.

These counters end at Alertmanager. Whether Alertmanager routed the alert to a person is its own
question; use the `alertmanager-query` skill for it.

## Duplicate pages and the way back to the rule

Alertmanager merges alerts with identical labels. Several vmalert replicas for high availability
must send identical labels, so a per-replica `-external.label` such as `replica=a` turns one alert
into one per replica, and each one pages. Alertmanager replicas must run as one cluster, and each
vmalert lists all of them in `-notifier.url`. Compare the labels of the copies with the
`alertmanager-query` skill. With `-external.alert.source` unset, each copy's `generatorURL` points
to `vmalert/alert` on the `-external.url` of the vmalert that sent it.

Alertmanager keeps no resolved alerts, and vmalert's counters have no per-alert history. For a
past page, only the receiver's own record, such as the channel, the pager or a webhook log, proves
what was delivered.
