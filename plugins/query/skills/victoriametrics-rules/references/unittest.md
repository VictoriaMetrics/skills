# Unit tests with vmalert-tool

`vmalert-tool unittest` runs rules on series you write by hand and compares the result with what
you expect. It needs no running vmalert or VictoriaMetrics. The test format is the Prometheus
`promtool` format, with `metricsql_expr_test` in place of `promql_expr_test`. See
https://docs.victoriametrics.com/victoriametrics/vmalert-tool/#unit-testing-for-rules.

`rules_test.yml`, next to `rules.yml`:

```yaml
rule_files:
  - rules.yml

evaluation_interval: 1m

tests:
  - name: short outage does not fire, long outage does
    interval: 1m
    input_series:
      - series: 'up{job="api", instance="host:9090"}'
        values: "1x4 0x2 1x5 0x9 1x10"
    alert_rule_test:
      - eval_time: 8m
        groupname: api
        alertname: InstanceDown
        exp_alerts: []
      - eval_time: 20m
        groupname: api
        alertname: InstanceDown
        exp_alerts:
          - exp_labels:
              job: api
              instance: host:9090
              severity: page
            exp_annotations:
              summary: "Instance host:9090 down"
```

The rule is `expr: up == 0` with `for: 5m`. The series is down for 3 minutes (5m to 7m), then for
10 minutes (14m to 23m). The alert fires only when the series has been down for `for`: here from
19m. The first case checks that the short outage does not fire. The second checks that the long
one fires with the right labels and annotations.

```bash
vmalert-tool unittest --files=rules_test.yml
```

- `1x4` means 5 points of 1: the value, then 4 more. `0+1x3` is `0 1 2 3`, and `_x3` is three
  missing points.
- `eval_time` counts from the test start, 2000-01-01T00:00:00Z.
- `evaluation_interval` replaces the group `interval` in the test.
- Add `-external.label=name=value` when a template uses `$externalLabels`.
- It takes only metric series as input, so it cannot test a `vlogs` rule.
