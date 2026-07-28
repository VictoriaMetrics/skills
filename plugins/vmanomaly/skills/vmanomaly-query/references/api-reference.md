# vmanomaly v1.30 API reference

This reference covers the stable workflows used by the vmanomaly skills. The running OpenAPI
document and model schemas remain authoritative.

## Contents

- [Common conventions](#common-conventions)
- [Runtime and compatibility](#runtime-and-compatibility)
- [Models and configuration](#models-and-configuration)
- [Server context and query proxy](#server-context-and-query-proxy)
- [Time-series characteristics](#time-series-characteristics)
- [Shared autotune](#shared-autotune)
- [Detection tasks](#detection-tasks)
- [Errors and safe retries](#errors-and-safe-retries)

## Common conventions

Base URL: `$VM_ANOMALY_URL`. Include `path_prefix` in this value when configured.

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Process health |
| `/metrics` | GET | Prometheus self-monitoring metrics |
| `/api/v1/server/buildinfo` | GET | Runtime and bundled UI versions |
| `/api/v1/compatibility` | GET | Stored-state compatibility |
| `/api/v1/models` | GET | Available model aliases |
| `/api/v1/model/schema` | GET | Model JSON schema |
| `/api/v1/model/validate` | POST | Validate one model spec |
| `/api/v1/config/validate` | POST | Validate full YAML configuration |
| `/api/v1/server/queries` | GET | Configured query aliases |
| `/api/v1/server/datasource` | GET | Configured datasource context |
| `/api/v1/query` | GET/POST | Proxy a datasource query |
| `/api/v1/timeseries/characteristics` | GET | Profile a bounded query sample |
| `/api/v1/autotune/tasks` | POST | Start shared autotune |
| `/api/v1/autotune/tasks/{id}` | GET/DELETE | Poll/cancel autotune |
| `/api/v1/anomaly_detection/limits` | GET | Detection-task capacity |
| `/api/v1/anomaly_detection/tasks` | POST/GET | Create/list detection tasks |
| `/api/v1/anomaly_detection/tasks/{id}` | GET/DELETE | Poll/cancel detection |
| `/api/vmanomaly/config.yaml` | GET | Generate example configuration |
| `/api/vmanomaly/example-alert-rule.yaml` | GET | Generate VMAlert rule |

Use JSON request bodies unless an endpoint explicitly accepts YAML or query parameters.
Times may be Unix seconds; durations use strings such as `5m`, `2w`, or `30d`.

`/health` is a point check. Production health should use the documented `/metrics` series together
with the official vmanomaly self-monitoring dashboard and alert rules, including scheduler-level
`vmanomaly_scheduler_alive` and `vmanomaly_scheduler_restarts_total` signals.

## Runtime and compatibility

### `GET /api/v1/server/buildinfo`

Returns the vmanomaly and bundled VMUI versions. Use it to establish runtime capabilities before
assuming a model or endpoint exists.

### `GET /api/v1/compatibility`

Checks persisted configuration/model/reader state against the current runtime. Optional query
parameter `version_to=X.Y.Z` checks a planned target instead.

Important response fields:

- `runtime_version`, `stored_version`
- `global_check.has_state`
- `global_check.is_compatible`
- `global_check.reason`
- `global_check.drop_everything`
- `component_assessment.models_to_purge`
- `component_assessment.should_purge_reader_data`

No state is a successful result, not an error. The endpoint diagnoses required cleanup but does
not perform it. The provided-config POST variant is not implemented in v1.30.

## Models and configuration

### `GET /api/v1/models`

Returns aliases supported by this build. Common v1.30 values include `temporal_envelope`,
`temporal_envelope_multivariate`, `mad_online`, `zscore_online`, `quantile_online`, `prophet`,
`holtwinters`, and Isolation Forest variants. Never replace the returned list with a hardcoded one.

### `GET /api/v1/model/schema?model_class=<alias>`

Returns parameter types, bounds, defaults, descriptions, and allowed values. Use the schema as an
allow-list whenever changing model class. Internal attachment/output fields may not appear in the
UI-oriented schema.

### `POST /api/v1/model/validate`

Accepts one JSON model spec containing `class`. A 201 response is successful. A 422 response
contains validation details; correct the spec rather than silently dropping user requirements.

### `POST /api/v1/config/validate`

Validates a full configuration without applying it. Send YAML with `Content-Type:
application/yaml`. Runtime deployment or hot reload is a separate user-controlled action.

### Generated artifacts

`GET /api/vmanomaly/config.yaml` accepts model/query/scheduler parameters and returns YAML.
`GET /api/vmanomaly/example-alert-rule.yaml` returns a VMAlert rule. Use `--data-urlencode` for
expressions and durations. Generated output still needs validation and human review.

## Server context and query proxy

### `GET /api/v1/server/queries`

Returns configured query aliases and expressions. Resolve aliases here before asking the user to
repeat an already configured query.

### `GET /api/v1/server/datasource`

Returns the configured server/UI datasource URLs and type. Do not expose credentials.

### `GET|POST /api/v1/query`

Proxies PromQL/MetricsQL or LogsQL through the configured reader path. Typical parameters:

- `query` (required)
- `start`, `end`, `step`
- `datasource_type` (`vm` or `vlogs`)
- optional `datasource_url`, `tenant_id`, `pass_auth_headers`

Use the product-specific companion query skill for discovery when installed. A successful empty
result does not prove that no data exists; first verify the query and label names.

## Time-series characteristics

### `GET /api/v1/timeseries/characteristics`

Profiles a bounded sample before model selection or autotune.

Parameters:

- `query` (required, non-empty)
- `start`, `end`
- `step` (use the final inference resolution)
- `datasource_type`, optional datasource override and tenant
- `timezone` for local-calendar analysis
- `short_gap_steps`
- `limit` (default 100)
- `verbose` for extra aggregate diagnostics without identifiers

Key response evidence:

- `eligible_series_count`, `eligible_series_share`, `coverage_threshold`
- `has_trend`, `trend.share`, `trend.direction_mode`
- `has_daily`, `has_weekly`, `has_monthly`
- `shape.flat_share`, `spiky_share`, `intermittent_share`
- `seasonalities.recommended` and per-profile summaries
- `stats.seriesLimitApplied`, `seriesEstimated`, `seriesLimitMode`

Interpret HOD/hour-of-day as a daily local-hour pattern and DOW/day-of-week as a weekly pattern.
Limited results are directional samples. Limited reads must fit one query chunk; on a split-chunk
422, shorten the interval or use a coarser step.

## Shared autotune

### `POST /api/v1/autotune/tasks`

Tunes one already selected model class across a bounded query sample. Required conceptual inputs:

- exact `query`
- `tuned_class_name`
- expected upper alert-volume constraint `anomaly_percentage`
- `start`, `end`, `step`
- explicit optimization budget

Useful controls:

- `limit`
- `use_profile_hints`
- `optimization_params.n_trials`, `timeout`
- `optimization_params.exact` for causal online-model evaluation
- `optimization_params.optimize_complexity` for fitted-state tie-breaking
- `optimized_business_params` only for business fields the user authorizes tuning
- `frozen_params` for fixed domain/model choices such as direction, holidays, or multivariate
  `groupby`

For multivariate models, keep group structure fixed rather than treating it as an optimizer
dimension. Treat offline-model tuning as a legacy or explicitly requested workflow, not a default
candidate path.

Creation returns a task ID immediately. Poll `GET /api/v1/autotune/tasks/{id}` until `done`,
`error`, or `canceled`.

On `done`, use:

- `result_data.data.modelConfig`: validated candidate to apply/test
- `result_data.data.bestParams`, `bestScore`
- `result_data.data.profile`
- `result_data.data.optimization`
- `result_data.stats`

This workflow returns a concrete one-time recommendation. It is different from deploying
`class: auto`, which retunes during the model fitting lifecycle.

There is no v1.30 autotune task-list or limits endpoint. Do not invent them.

## Detection tasks

### `GET /api/v1/anomaly_detection/limits`

Check available capacity before creating a task. A 429 from task creation means capacity is
exhausted; wait or ask before canceling other work.

### `POST /api/v1/anomaly_detection/tasks`

Important fields:

- `query`, `step`, `datasource_url` when not resolved from server context
- `fit_window`, `fit_every`
- `start_infer_s`, `end_infer_s`
- validated `model_spec`
- `exact` and `infer_every` where applicable

For UI/API exploration with an online model, a very large `fit_every` can intentionally preserve
one causal state through the displayed interval. Production periodic cadence is a separate choice.

Task results can contain `y`, `yhat`, bounds, and anomaly score depending on model output. The API
may constrain output fields for response size; do not copy that response-oriented `provide_series`
setting into production without an explicit reason.

### Polling and cancellation

Poll one task every few seconds. Treat `done`, `error`, and `canceled` as terminal. Use DELETE for
cooperative cancellation only when requested. Never create duplicate tasks to simulate polling.

## Errors and safe retries

| Status | Meaning | Response |
|---|---|---|
| 400 | malformed/unsupported request | Correct the request; do not retry blindly |
| 404 | unknown route/task/model | Recheck build info, path prefix, alias, or task ID |
| 422 | validation/query error | Read details; correct fields or query window |
| 429 | task capacity reached | Wait, reduce concurrency, or ask before cancellation |
| 500 | server/runtime failure | Preserve error details and inspect logs/metrics |

Retry only transient connection/server failures, with a bounded count. Validation failures are not
transient. Keep tool calls sequential when later calls depend on IDs or results from earlier ones.
