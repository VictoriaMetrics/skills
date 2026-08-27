---
name: vmanomaly-query
description: >
  Operate VictoriaMetrics Anomaly Detection (vmanomaly) through its HTTP API. Use when checking health, versions, persisted-state compatibility, self-monitoring metrics, available models, model schemas, server queries, time-series characteristics, shared autotune, or asynchronous detection tasks. Also use for generating and validating vmanomaly configuration or alert-rule YAML. Triggers on vmanomaly API, anomaly tasks, model validation, model schema, compatibility, Temporal Envelope, time-series profiling, and vmanomaly autotune.
allowed-tools: Bash(curl:*), Bash(jq:*)
---

# vmanomaly API

Operate a running vmanomaly v1.30+ instance through bounded, explicit API calls. Prefer live schemas and server responses over static assumptions.

## Environment and authentication

```bash
# Include any configured path prefix in the base URL.
export VM_ANOMALY_URL="https://vmanomaly.example.com"
# Use /dev/null for unauthenticated local instances. For authenticated instances, point this to
# a mode-0600 curl config containing: header = "Authorization: Bearer <token>"
export VM_CURL_CONFIG="${VM_CURL_CONFIG:-/dev/null}"
```

Keep credentials out of process arguments and use the same config for every request:

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/health" | jq .
```

Never print or create the credential file. Ask for `VM_ANOMALY_URL` when it is unset.

## Start with a runtime preflight

Run these checks before configuration, review, autotune, or migration work:

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/health" | jq .

curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/server/buildinfo" | jq .

curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/compatibility" | jq .
```

Interpret compatibility conservatively:

- `global_check.has_state=false`: no persisted state needs migration.
- `global_check.is_compatible=true`: the covered vmanomaly-managed state can be reused.
- `global_check.drop_everything=true`: report that all persisted state must be dropped; do not perform the drop automatically.
- `component_assessment.models_to_purge` or `should_purge_reader_data`: report the scoped cleanup.
- Use `?version_to=X.Y.Z` to assess the stored state against a planned target release.

Compatibility covers vmanomaly-managed state, supported readers, and built-in models, not custom model code, dependencies, or state; before upgrading to v1.30.3+, custom many-to-one models relying on `is_multivariate = True` must declare `topology = ModelTopology.MANY_TO_ONE`.

Only GET compatibility is implemented. Do not invent a POST endpoint for arbitrary provided configs. For configuration syntax, use `/api/v1/config/validate` instead.

## Discover capabilities before using them

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/models" | jq .

curl -q --config "$VM_CURL_CONFIG" -sG \
  --data-urlencode 'model_class=temporal_envelope' \
  "$VM_ANOMALY_URL/api/v1/model/schema" | jq .
```

Treat `/api/v1/models` and `/api/v1/model/schema` as authoritative. Do not carry parameters between model classes unless the target schema exposes them.

## Validate before running

Validate one model:

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  -X POST -H 'Content-Type: application/json' \
  -d '{"class":"temporal_envelope","seasonalities":["hod_smooth","dow_smooth"]}' \
  "$VM_ANOMALY_URL/api/v1/model/validate" | jq .
```

Validate a complete configuration:

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  -X POST -H 'Content-Type: application/yaml' \
  --data-binary @config.yaml \
  "$VM_ANOMALY_URL/api/v1/config/validate" | jq .
```

Validation does not apply or reload a configuration.

## Inspect the running server

```bash
# Configured query aliases and expressions.
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/server/queries" | jq .

# Configured datasource context. Keep only documented fields and redact URL user information.
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/server/datasource" | jq '
    with_entries(select(.key | IN("server_datasource_url", "ui_datasource_url", "ui_datasource_type")))
    | with_entries(
        if (.value | type) == "string" and (.key | endswith("_url"))
        then .value |= sub("://[^/@]+@"; "://<redacted>@")
        else .
        end
      )'

# Prometheus-format self-monitoring metrics.
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/metrics?name[]=vmanomaly_scheduler_alive&name[]=vmanomaly_scheduler_restarts_total&name[]=vmanomaly_model_run_errors&name[]=vmanomaly_model_runs_skipped"
```

Treat `/health` as a point-in-time preflight, not production monitoring. For a running deployment, recommend scraping or pushing the documented [self-monitoring metrics](https://docs.victoriametrics.com/anomaly-detection/components/monitoring/#metrics-generated-by-vmanomaly), installing the [Grafana dashboard](https://docs.victoriametrics.com/anomaly-detection/self-monitoring/#grafana-dashboard), and reviewing the supplied [alerting rules](https://docs.victoriametrics.com/anomaly-detection/self-monitoring/#alerting-rules). Prioritize service availability, scheduler liveness/restarts, reload failures, model errors/skips, I/O error rates, and resource pressure. Do not deploy rules or dashboards without user approval.

When installed, use `victoriametrics-query` to verify that self-monitoring series are ingested and the expected rules are loaded; use `alertmanager-query` to inspect active, silenced, or inhibited vmanomaly alerts.

## Profile a query before choosing a model

An exact non-empty query is required. If the user supplied one, reuse it. Otherwise resolve a configured query alias or ask the user; never invent a production query from a metric description.

```bash
QUERY='sum(rate(http_requests_total{job="api"}[5m])) by (service)'
TIMEZONE='America/New_York'
curl -q --config "$VM_CURL_CONFIG" -sG \
  --data-urlencode "query=$QUERY" \
  --data-urlencode 'start=<unix-seconds>' \
  --data-urlencode 'end=<unix-seconds>' \
  --data-urlencode 'step=5m' \
  --data-urlencode "timezone=$TIMEZONE" \
  --data-urlencode 'limit=100' \
  "$VM_ANOMALY_URL/api/v1/timeseries/characteristics" | jq .
```

Use the same `step` for profiling, autotune, and the final task/config. Treat a limited response as a sample, not an exact population summary. If a limited read returns a split-chunk `422`, use a shorter interval or coarser step.

## Run shared autotune

Choose `tuned_class_name` first from the profile, business intent, `/api/v1/models`, and schema. Shared v1.30 autotune does not choose the model class.

```bash
jq -n --arg query "$QUERY" --arg timezone "$TIMEZONE" '{
    query:$query,
    "tuned_class_name":"temporal_envelope",
    "anomaly_percentage":0.02,
    "start":1710000000,
    "end":1711209600,
    "step":"5m",
    timezone:$timezone,
    "limit":100,
    "use_profile_hints":true,
    "optimization_params":{"n_trials":64,"timeout":30,"exact":true,"optimize_complexity":true},
    "frozen_params":{"detection_direction":"above_expected"}
  }' | curl -q --config "$VM_CURL_CONFIG" -s \
  -X POST -H 'Content-Type: application/json' --data-binary @- \
  "$VM_ANOMALY_URL/api/v1/autotune/tasks" | jq .
```

Tell the user the trial/time budget before creating the task. Poll one task sequentially:

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/autotune/tasks/<task_id>" | jq .
```

Treat `done`, `error`, and `canceled` as terminal. On `done`, apply `result_data.data.modelConfig` directly, validate it, and test it. Do not replace this concrete one-time recommendation with `class: auto`; the deployable auto wrapper has a different lifecycle. Business policies in this result remain model-spec fields for task/UI compatibility; move them to the attached query only when constructing a v1.30.2+ deployment configuration. Use DELETE only when the user asks to cancel:

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  -X DELETE "$VM_ANOMALY_URL/api/v1/autotune/tasks/<task_id>" | jq .
```

## Run bounded detection tasks

Check capacity first:

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/anomaly_detection/limits" | jq .
```

Create a task only after validating `model_spec`. The v1.30.3 task contract requires an explicit `datasource_url`; reuse the configured datasource URL when appropriate:

```bash
DATASOURCE_URL='<configured-or-explicit-datasource-url>'
jq -n --arg query "$QUERY" --arg datasource_url "$DATASOURCE_URL" '{
    query:$query,
    datasource_url:$datasource_url,
    "step":"5m",
    "fit_window":"30d",
    "fit_every":"1000d",
    "start_infer_s":1710000000,
    "end_infer_s":1710086400,
    "exact":true,
    "model_spec":{"class":"temporal_envelope","seasonalities":["hod_smooth","dow_smooth"]}
  }' | curl -q --config "$VM_CURL_CONFIG" -s \
  -X POST -H 'Content-Type: application/json' --data-binary @- \
  "$VM_ANOMALY_URL/api/v1/anomaly_detection/tasks" | jq .
```

Use `exact:true` for causal online-model evaluation. Poll sequentially and never create duplicate tasks merely because a task is still running.

## Generate deployment artifacts

Use `/api/vmanomaly/config.yaml` for an example configuration and `/api/vmanomaly/example-alert-rule.yaml` for a VMAlert rule. Pass values with `--data-urlencode`. The config endpoint preserves compatibility-oriented model-level business fields. For v1.30.2+ deployment YAML, move `data_range`, `detection_direction`, `min_dev_from_expected`, and `min_rel_dev_from_expected` to `reader.queries.<alias>`, consider `reader.workers: 0` for bounded datasource concurrency, and validate the resulting complete configuration before presenting it.

## Optional companion skills

- Use `victoriametrics-query` when available to discover metric names, labels, cardinality, or existing alert/rule queries before constructing PromQL/MetricsQL.
- Use `victorialogs-query` when the datasource is VictoriaLogs and LogsQL discovery is needed.
- Use `alertmanager-query` to check active alerts or avoid duplicating existing alerting intent.

These are optional enhancements. Continue through vmanomaly server/proxy endpoints when they are not installed.

## Reference

Read `references/api-reference.md` for endpoint parameters, response fields, error handling, and v1.30 task semantics.
