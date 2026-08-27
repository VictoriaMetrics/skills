---
name: vmanomaly-config
description: >
  Design, tune, validate, and test VictoriaMetrics vmanomaly configurations for known metrics or LogsQL queries. Use when choosing static alerting versus ML, selecting a vmanomaly model, configuring Temporal Envelope, building deployment YAML, tuning anomaly sensitivity, or creating VMAlert rules. Trigger on anomaly configuration, model selection, shared autotune, seasonal anomaly detection, forecasting, or "how should I monitor this metric?" Do not use for open-ended discovery across unknown signals.
allowed-tools: Bash(curl:*), Bash(jq:*), Read
---

# vmanomaly configuration builder

Turn a known monitoring intent into a validated vmanomaly v1.30+ configuration. ML must earn its operational cost: first decide whether a static rule expresses the failure condition more clearly.

Read `references/model-selection.md` before selecting a model or its parameters. When producing a continuously running deployment, also read `references/deployment-readiness.md` and apply only the controls whose conditions match.

## Environment

```bash
export VM_ANOMALY_URL="https://vmanomaly.example.com"
# Use /dev/null without authentication. For authenticated instances, point this to a mode-0600
# curl config containing: header = "Authorization: Bearer <token>"
export VM_CURL_CONFIG="${VM_CURL_CONFIG:-/dev/null}"
```

Include any configured path prefix in `VM_ANOMALY_URL`. Never print or create the credential file. Ask for the URL when it is unavailable.

## Workflow

### 1. Establish intent and obtain the exact query

Collect or infer:

- the exact PromQL/MetricsQL or LogsQL expression;
- spikes, drops, level shifts, seasonal breaks, or trend breaks to detect;
- direction: `above_expected`, `below_expected`, or both;
- desired reaction time and query step;
- IANA timezone used by the production query and calendar profiles;
- known physical bounds and insignificant absolute/relative deviations;
- sensitivity preference and acceptable upper detection rate.

If the model-query field is empty but the user already supplied a query, use it for profiling and recommend placing it in the UI query input. If no query exists, ask for one. Do not invent a production query from a metric description.

When installed, `victoriametrics-query` or `victorialogs-query` may help discover names, labels, and valid expressions. Their absence must not block this skill.

### 2. Triage static alerting versus ML

Prefer a static VMAlert rule when a clear bad value exists:

| Signal shape | Better first choice |
|---|---|
| near-zero error/restart count | `> threshold for duration` |
| monotonic capacity fill | percentage threshold plus `predict_linear` |
| binary/up-down state | direct threshold, `absent()`, or `changes()` |
| expiry or hard safety limit | direct threshold |

Use vmanomaly when normal varies by time, instance, workload, or a drifting baseline; when daily, weekly, monthly, or holiday structure matters; or when a cross-series relationship is the signal. Present this decision before spending an autotune budget.

### 3. Run the runtime preflight

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/health" | jq .
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/server/buildinfo" | jq .
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/compatibility" | jq .
```

Treat the compatibility response as a preflight, not a cleanup action:

- no stored state is healthy;
- report `drop_everything`, models to purge, or reader-data cleanup;
- never delete state without explicit user approval;
- use `?version_to=X.Y.Z` for a planned upgrade.

Compatibility covers vmanomaly-managed state, supported readers, and built-in models, not custom model code, dependencies, or state; before upgrading to v1.30.3+, custom many-to-one models relying on `is_multivariate = True` must declare `topology = ModelTopology.MANY_TO_ONE`.

Only the GET compatibility check exists in v1.30.

### 4. Profile real data

Use the same `step` that the final task/config will use:

```bash
QUERY='<exact-query>'
TIMEZONE='<IANA-timezone>'
curl -q --config "$VM_CURL_CONFIG" -sG \
  --data-urlencode "query=$QUERY" \
  --data-urlencode 'start=<unix-seconds>' \
  --data-urlencode 'end=<unix-seconds>' \
  --data-urlencode 'step=5m' \
  --data-urlencode "timezone=$TIMEZONE" \
  --data-urlencode 'limit=100' \
  "$VM_ANOMALY_URL/api/v1/timeseries/characteristics" | jq .
```

Use measured trend, daily/weekly/monthly profiles, shape, eligibility, and coverage rather than guessing from the metric name. A limited result is a sample. If a limited read returns a split-chunk 422, shorten the interval or use a coarser step.

### 5. Discover and select a supported model

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/models" | jq .
curl -q --config "$VM_CURL_CONFIG" -sG \
  --data-urlencode 'model_class=temporal_envelope' \
  "$VM_ANOMALY_URL/api/v1/model/schema" | jq .
```

Use the live alias list and schema as authoritative. Rebuild the model spec when changing class; never carry stale parameters across classes.

Default hierarchy:

1. Start with `temporal_envelope` for any non-trivial temporal profile: trend, calendar patterns, holidays, persistent shifts, forecasts, or uncertainty about whether a simple stationary baseline is sufficient.
2. Use `mad_online` or `zscore_online` only when profiling confirms simple, non-seasonal, relatively stable data. Prefer MAD for skewed, heavy-tailed, or outlier-contaminated data; use Z-score only when the distribution is stable/light-tailed and standard-deviation magnitude is meaningful.
3. For aligned channels where their relationship is the anomaly, start with `temporal_envelope_multivariate`.
4. Do not introduce an offline model in the normal recommendation flow. Discuss one only when reviewing a legacy configuration, when the user explicitly requests it, or when a controlled comparison has already established a material benefit that an online model cannot provide.

### 6. Map domain knowledge to public controls

- Fix `detection_direction` when business intent is known, and map insignificant absolute/relative deviations to `min_dev_from_expected` and `min_rel_dev_from_expected`.
- In v1.30.2+ deployable YAML, place `data_range`, `detection_direction`, `min_dev_from_expected`, and `min_rel_dev_from_expected` under `reader.queries.<alias>`. Query values are authoritative across attached models; model-level values remain compatible local fallbacks but are deprecated.
- For VMUI or an ad-hoc detection task, keep these fields in `model_spec`: the UI suggestion/query contract does not expose per-query business-policy fields. The backend maps `data_range` to the temporary query and resolves the other fields as model-local compatibility values.
- Set model-level `clip_predictions` only when forecast and interval outputs should be clipped to that domain.
- Use `min_n_samples_seen` to suppress scores during cold-start; express its duration as samples multiplied by query step.
- For stable MAD, Z-score, or online-quantile data, consider `history_strength > 1` instead of many extra fit cycles; keep enough history to cover every required seasonal phase.
- Select only calendar presets supported by the profile. Temporal Envelope profiles are timezone- and DST-aware; set `reader.queries.<alias>.tz` (or the reader-level `tz`) to the same IANA timezone used during profiling.
- Keep `forecast_at` empty unless the user needs future-state forecasting or capacity planning.
- Keep multivariate `groupby`, holidays, and other domain structure fixed during autotune.

### 7. Choose direct configuration or shared autotune

For a direct configuration, begin with schema defaults and change only justified controls.

For shared autotune, first select the model class. State the trial/time budget, then create one bounded task. Use causal exact validation for online models:

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

Poll `GET /api/v1/autotune/tasks/{task_id}` sequentially. On success, use the concrete `result_data.data.modelConfig`, validate it, and test it. Do not substitute `class: auto`; that wrapper retunes during each fit and is a separate, explicitly chosen lifecycle. Autotune still returns a model spec: keep frozen business fields there for VMUI/ad-hoc testing, but move them to the corresponding query when assembling v1.30.2+ deployment YAML.

### 8. Validate and test

Validate the model spec:

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  -X POST -H 'Content-Type: application/json' \
  -d @model.json "$VM_ANOMALY_URL/api/v1/model/validate" | jq .
```

Validate full YAML without applying it:

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  -X POST -H 'Content-Type: application/yaml' --data-binary @config.yaml \
  "$VM_ANOMALY_URL/api/v1/config/validate" | jq .
```

Then check capacity and run a bounded detection task using the validated model. The v1.30.3 task contract requires an explicit `datasource_url`; reuse the configured datasource URL when appropriate:

```bash
curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/anomaly_detection/limits" | jq .

DATASOURCE_URL='<configured-or-explicit-datasource-url>'
jq -n --arg query "$QUERY" --arg datasource_url "$DATASOURCE_URL" --slurpfile model model.json '{
    query:$query,
    datasource_url:$datasource_url,
    step:"5m",
    fit_window:"30d",
    fit_every:"1000w",
    start_infer_s:1710000000,
    end_infer_s:1710086400,
    exact:true,
    model_spec:$model[0]
  }' | curl -q --config "$VM_CURL_CONFIG" -s \
  -X POST -H 'Content-Type: application/json' --data-binary @- \
  "$VM_ANOMALY_URL/api/v1/anomaly_detection/tasks" | jq .

curl -q --config "$VM_CURL_CONFIG" -s \
  "$VM_ANOMALY_URL/api/v1/anomaly_detection/tasks/<task_id>" | jq .
```

Poll the returned task ID sequentially until `done`, `error`, or `canceled`. For online models use `exact:true` and default to an effectively disabled refit cadence such as `fit_every: 1000w`, so the initial fit evolves causally during inference. Configure periodic refits only when explicitly needed.

Evaluate detections visually and against known events. Without ground-truth labels, call the observed fraction a **detection rate**, not a false-positive rate. Ask the user which detections were useful before tightening the model.

### 9. Deliver deployable artifacts

Provide:

- the static rule or complete vmanomaly YAML;
- a VMAlert rule for the produced anomaly score;
- rationale tied to profile evidence and business intent;
- query step, fit window/cadence, warmup, expected reaction time, and resource caveats;
- validation/test results and assumptions requiring production verification.
- self-monitoring integration, with the official dashboard and alert rules recommended for production rather than relying on point-in-time health checks.
- justified state restoration, retention, hot-reload, persistence, and workload-distribution choices from `references/deployment-readiness.md`.

Generated `/api/vmanomaly/config.yaml` and `/api/vmanomaly/example-alert-rule.yaml` output is a starting point, not proof of correctness. The config endpoint preserves the VMUI/model-spec compatibility shape; before presenting v1.30.2+ deployment YAML, move the four stable business policies to `reader.queries.<alias>`, add `reader.workers` when appropriate, and validate the final configuration.

## Safety

- API validation and tasks do not deploy or hot-reload configuration.
- Obtain approval before applying configs, creating persistent alert rules, or deleting state.
- Bound samples, time ranges, series limits, trial counts, and concurrent tasks.
- Never infer that empty data means the metric does not exist until the query and labels are checked.
