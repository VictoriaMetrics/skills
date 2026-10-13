# Writing a new rule

The steps below point back to Workflow B in `SKILL.md` for the checks.

## 1. Run the expression before writing the rule around it

Use the `victoriametrics-query` skill for MetricsQL, or `victorialogs-query` for LogsQL. An
expression which returns nothing produces a rule which never fires, and no later check reports
that as an error.

## 2. Write the rule

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
the alert's own labels templated into the URL. The person woken at 03:00 starts there. Workflow B
step 3 shows the rendered link, so check it resolves before trusting it.

Labels accept only `$labels`, `$value` and `$expr`. Never put `$value` in a label: each new value
makes a new alert, so `for` never elapses.

`for` holds the alert until the condition has been true that long. `keep_firing_for` holds it
after the condition clears, which stops a flapping alert from resolving and re-firing.

## 3. Check when it would fire

Use Workflow B step 4 against the window of a real past incident. Silence there means the rule would
have missed it. For a `vlogs` rule, use the `stats_query_range` check in `references/logs-rules.md`.
A recording rule never fires, so skip this step for it.

## 4. Deploy, reload, then verify against the live instance

Put the rule in a file that vmalert loads through `-rule`. Then reload:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --fail-with-body -X POST "$VMALERT_URL/-/reload"
```

`/-/reload` sends vmalert a SIGHUP to re-read its rule files, and answers 200 before it reads
them. A 401 means `-reloadAuthKey` is set. A file that fails to parse still answers 200, so check
that `vmalert_config_last_reload_successful` in `/metrics` is 1. Then run Workflow B steps 1 and 2
and confirm `health=ok`, `lastError` empty, and `fetched` greater than zero.
