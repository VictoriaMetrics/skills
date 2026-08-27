---
name: vmanomaly-review
description: >
  Audit an existing VictoriaMetrics vmanomaly configuration against runtime capabilities and real data. Use when reviewing model-data fit, scheduler cadence, persisted-state compatibility, cold start, excessive detections, missing anomalies, output cardinality, or upgrade readiness. Trigger on vmanomaly config review, false-positive investigation, detection quality, model effectiveness, compatibility, and "is my anomaly detection working?" Use vmanomaly-config instead when building a new configuration from scratch.
allowed-tools: Bash(curl:*), Bash(jq:*), Read
---

# vmanomaly configuration reviewer

Review a running or proposed vmanomaly v1.30+ configuration without mutating it. Separate facts, measured evidence, and hypotheses. A static rule may be a better outcome than an ML model.

Read `references/evaluation-guide.md` before judging detections or model-data fit.

## Environment

```bash
export VM_ANOMALY_URL="https://vmanomaly.example.com"
# Use /dev/null without authentication. For authenticated instances, point this to a mode-0600
# curl config containing: header = "Authorization: Bearer <token>"
export VM_CURL_CONFIG="${VM_CURL_CONFIG:-/dev/null}"
```

Include any path prefix in the base URL. Never print or create the credential file.

## Workflow

### 1. Load and summarize the configuration

Read the YAML path supplied by the user, including `configRawYaml` embedded in a Kubernetes resource. Summarize:

- query aliases and expressions;
- model aliases/classes, parameters, queries, and schedulers;
- scheduler `infer_every`, `fit_every`, and `fit_window`;
- datasource type and relevant reader settings;
- expected reaction time and anomaly intent if known.

Group queries by model so shared parameters and multivariate relationships are visible. Ask for an exact missing query; do not invent one.

### 2. Run compatibility and capability preflight

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/health" | jq .
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/server/buildinfo" | jq .
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/compatibility" | jq .
```

Report incompatibility and scoped cleanup; do not execute cleanup. No stored state is healthy. Use `?version_to=X.Y.Z` when reviewing an upgrade. Compatibility covers vmanomaly-managed state, supported readers, and built-in models, not custom model code, dependencies, or state; before upgrading to v1.30.3+, custom many-to-one models relying on `is_multivariate = True` must declare `topology = ModelTopology.MANY_TO_ONE`. Only GET exists in v1.30.

For deployed instances, also verify that self-monitoring metrics are collected and that the official dashboard and alerting rules cover service health, scheduler liveness/restarts, reload failures, model errors/skips, I/O failures, and resource pressure. A successful `/health` response alone is insufficient production evidence.

Discover runtime aliases and fetch the schema for every configured class:

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/models" | jq .
curl -q --config "$VM_CURL_CONFIG" -sG \
  --data-urlencode 'model_class=<alias>' \
  "$VM_ANOMALY_URL/api/v1/model/schema" | jq .
```

### 3. Perform static validation

Validate the full YAML:

```bash
CONFIG_PATH='<user-supplied-yaml-path>'
curl -q --config "$VM_CURL_CONFIG" -s \
  -X POST -H 'Content-Type: application/yaml' --data-binary "@$CONFIG_PATH" \
  "$VM_ANOMALY_URL/api/v1/config/validate" | jq .
```

Also inspect:

- every query/model/scheduler reference resolves and no important component is orphaned;
- every model parameter exists in that exact class schema; use full-config validation for reader, scheduler, writer, and top-level fields;
- `infer_every` meets the user's reaction-time requirement;
- fit history covers configured calendar cycles;
- known data bounds and significance thresholds match query units;
- `min_n_samples_seen` can complete within available history;
- multivariate `groupby` and channel counts match the intended dependency groups;
- requested `provide_series` does not create accidental output cardinality;
- offline models have a suitable refit cadence.
- for v1.30.2+ deployment YAML, stable `data_range`, `detection_direction`, `min_dev_from_expected`, and `min_rel_dev_from_expected` policies are query-level. Report model-level placement as a deprecated compatible fallback, not a validation failure; explicit query values take precedence.
- `reader.workers` bounds datasource concurrency, while `settings.n_workers` controls model processes and `settings.native_threads_per_worker` bounds native threads per process.

Changing class requires reconstructing the spec from the new schema, not deleting errors one by one until validation passes.

### 4. Re-triage each signal

Flag metrics where static alerting is clearer: hard limits, expiry, binary state, monotonic fill, or near-zero failures. Avoid duplicating a precise static alert with a less interpretable model.

Keep ML for natural variance, differing per-series baselines, trend/calendar behavior, persistent shifts, or cross-series dependency anomalies.

### 5. Profile each exact query

Use the configured query step and timezone, and a history window long enough for claimed seasonality:

```bash
QUERY='<exact-query>'
TIMEZONE='<configured-IANA-timezone>'
curl -q --config "$VM_CURL_CONFIG" -sG \
  --data-urlencode "query=$QUERY" \
  --data-urlencode 'start=<unix-seconds>' \
  --data-urlencode 'end=<unix-seconds>' \
  --data-urlencode 'step=<configured-step>' \
  --data-urlencode "timezone=$TIMEZONE" \
  --data-urlencode 'limit=100' \
  "$VM_ANOMALY_URL/api/v1/timeseries/characteristics" | jq .
```

Compare measured trend, profile shape, seasonalities, eligible share, coverage, and series count with the configured class and profiles. Limited results are samples. Do not extrapolate exact population counts from them.

Model-fit expectations:

- non-trivial trend/calendar/holiday/shift profile, or uncertainty about a simple stationary baseline: `temporal_envelope` is the preferred first check;
- confirmed simple, non-seasonal, heavy-tailed or outlier-contaminated profile: `mad_online`;
- confirmed simple, stable/light-tailed profile: `zscore_online`;
- dependency anomaly: `temporal_envelope_multivariate`.

Do not recommend an offline model as a fallback. When reviewing one, treat it as a legacy or explicitly requested choice and compare it with the corresponding online model.

### 6. Reproduce with a bounded task

Check capacity, then create one bounded task with the exact validated model specification:

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/anomaly_detection/limits" | jq .

MODEL_SPEC_JSON='<validated-model-json>'
DATASOURCE_URL='<configured-or-explicit-datasource-url>'
STEP='<configured-step>'
FIT_WINDOW='<configured-fit-window>'
FIT_EVERY='<exploratory-fit-cadence>'
START_INFER_S='<unix-seconds>'
END_INFER_S='<unix-seconds>'
jq -n \
  --arg query "$QUERY" \
  --arg datasource_url "$DATASOURCE_URL" \
  --arg step "$STEP" \
  --arg fit_window "$FIT_WINDOW" \
  --arg fit_every "$FIT_EVERY" \
  --argjson start_infer_s "$START_INFER_S" \
  --argjson end_infer_s "$END_INFER_S" \
  --argjson model "$MODEL_SPEC_JSON" '{
    query:$query,
    datasource_url:$datasource_url,
    step:$step,
    fit_window:$fit_window,
    fit_every:$fit_every,
    start_infer_s:$start_infer_s,
    end_infer_s:$end_infer_s,
    exact:true,
    model_spec:$model
  }' | curl -q --config "$VM_CURL_CONFIG" -s \
  -X POST -H 'Content-Type: application/json' --data-binary @- \
  "$VM_ANOMALY_URL/api/v1/anomaly_detection/tasks" | jq .

curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/anomaly_detection/tasks/<task_id>" | jq .
```

Poll sequentially until `done`, `error`, or `canceled`. Use `exact:true` for causal online-model evaluation. Keep query step, timezone, direction, data bounds, and significance thresholds aligned with production.

For an exploratory online task, a `fit_every` longer than the inference range preserves a single continuous state. This is not automatically the right production cadence.

Do not create duplicates while a task is running. Task creation and config validation are read-only with respect to deployment; applying changes is not.

### 7. Evaluate evidence correctly

Without labels or user-confirmed events:

- report **detection rate**, never claim a false-positive rate;
- inspect representative detections across time and labelsets;
- ask the user which were useful, expected events, or noise;
- check cold-start, seasonal boundaries, missing data, and regime transitions separately.

With labels, report precision, recall, F1, detection delay, and settled-regime false positives as appropriate. Prefer forward/causal validation for online models.

### 8. Prove proposed fixes

Change the smallest justified set, validate it, and rerun the same bounded interval. Compare:

- useful detections and missed confirmed events;
- detection rate or labeled precision/recall;
- forecast/boundary behavior when supported;
- warmup and adaptation delay;
- compute/state/output-cardinality impact.

Typical fixes include removing unsupported seasonal profiles, widening/narrowing the ordinary envelope, freezing direction/domain thresholds, extending fit history, splitting heterogeneous queries, adding multivariate grouping, or choosing a simpler/static detector.

Shared autotune may produce a candidate after model class is chosen. Use `exact:true` for online models and apply the returned concrete `modelConfig`; do not silently convert it to `class: auto`.

### 9. Report

For each query/model provide:

- verdict: pass, needs change, or replace with static rule;
- evidence from schema, compatibility, profile, and bounded test;
- severity and operational consequence;
- minimal proposed change and before/after result;
- assumptions, confidence, and follow-up observation window.

Separate confirmed faults from hypotheses. A visually unusual point is not automatically an anomaly, and an empty query result is not automatically proof of missing data.

## Optional companion skills

- `victoriametrics-query`: verify PromQL/MetricsQL, self-monitoring ingestion, labels, cardinality, and loaded vmanomaly alert rules.
- `victorialogs-query`: validate LogsQL and correlate log behavior.
- `alertmanager-query`: inspect active, silenced, or inhibited vmanomaly alerts before declaring service health or duplicated intent.
- `investigating-with-observability`: correlate confirmed detection windows with logs/traces.
- cardinality-analysis skills: assess excessive series/output fan-out.

These integrations improve evidence but are not prerequisites; continue using vmanomaly proxy and server endpoints when they are absent.

## Safety

- Do not apply configs, create persistent rules, purge state, or cancel another user's task without explicit approval.
- Bound time windows, series limits, and task concurrency.
- Preserve exact queries, timestamps, and errors in the report, but redact credentials.
