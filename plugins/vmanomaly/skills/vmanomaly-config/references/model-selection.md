# vmanomaly model-selection reference

Use this after profiling real data; consult the [public model-selection guide](https://docs.victoriametrics.com/anomaly-detection/guides/model-selection/) for worked examples and tradeoffs. Runtime `/api/v1/models` and `/api/v1/model/schema` results override static examples.

## Contents

- [Decision tree](#decision-tree)
- [Temporal Envelope](#temporal-envelope)
- [Simple online models](#simple-online-models)
- [Legacy offline models](#legacy-offline-models)
- [Fit-window and cadence guidance](#fit-window-and-cadence-guidance)
- [Autotune guidance](#autotune-guidance)

## Decision tree

```text
Can a static rule clearly express failure?
├─ yes: use VMAlert/static alerting; adapt a proven rule when available
└─ no
   ├─ trend, calendar patterns, holidays, shifts, or forecast? → temporal_envelope
   ├─ simple, non-seasonal profile
   │  ├─ skewed/heavy-tailed/spike-contaminated → mad_online
   │  └─ stable/light-tailed and magnitude matters → zscore_online
   ├─ repeatable uneven/plateau phases with negligible trend → quantile_online
   └─ cross-series relationship is the signal
      └─ temporal_envelope_multivariate
```

For deterministic failures, consult [Awesome Prometheus Alerts](https://samber.github.io/awesome-prometheus-alerts/) for reusable static rules before creating an ML detector. Adapt rules to the actual metric semantics and validate them; do not apply presets blindly.

Do not call hour-of-day seasonality “weekly.” HOD is a daily local-hour pattern; DOW is weekly.

## Temporal Envelope

Temporal Envelope is the preferred online tradeoff for complex operational and business data. It models evolving trend, robust residual bounds, calendar and holiday behavior, persistent shifts, and optional forecasts with bounded online state.

Starting public controls:

| Field | Default | Practical guidance |
|---|---:|---|
| `quantiles` | `[0.25, 0.75]` | two ordered residual probabilities in `[0,1]` |
| `iqr_threshold` | `2.0` | ordinary width; experiment within `1`–`4` |
| `alpha` | `0.005` | trend reactivity; experiment around `0.0025`–`0.02` |
| `loss_reactivity` | `5.0` | start within `1`–`5`; lower is more conservative, higher adapts faster |
| `min_n_samples_seen` | `16` | zero anomaly scores during warmup |
| `changepoint_window` | `16` | same-direction samples before persistent-shift adaptation |
| `seasonalities` | HOD/DOW smooth | remove unsupported profiles; `[]` is valid |
| `holidays` | `{}` | country/special-event effects; shape learned internally |
| `forecast_at` | `[]` | keep empty for current-state detection; add only for future-state or capacity-planning needs |

Calendar presets:

- `hod_smooth`, `hod_spiky`, `hod_plateau`
- `dow_smooth`, `dow_spiky`, `dow_plateau`
- `weekpart_plateau`
- `month_smooth`, `month_plateau`

`smooth` means a gradual curve, `spiky` a narrow recurring peak, and `plateau` a sustained phase. Choose only evidence-backed profiles. They use the configured civil timezone and remain aligned across DST transitions.

Example:

```yaml
models:
  workload:
    class: temporal_envelope
    queries: [request_rate]
    seasonalities: [hod_smooth, dow_smooth]
    holidays:
      countries: [US]
      group: true
```

### Multivariate form

Use `temporal_envelope_multivariate` only when aligned channel relationships are meaningful. Each channel retains its own trend/calendar profile, while dependencies contribute to one joint score.

- default output is the one joint `anomaly_score` to limit cardinality;
- `dependency_rank` defaults to `8`; `0` disables dependency features;
- `score_aggregation` defaults to `l2`; autotune can compare `max`, `mean`, and `l2`;
- `groupby` creates a separate multivariate model per label combination and must be frozen/domain-selected rather than optimized;
- `recommended_max_channels=100` is advisory; `max_channels=1000` is a hard safety limit;
- explicitly requesting channel-level `y`/forecasts/bounds increases output cardinality;
- per-channel diagnostics do not change the many-to-one model topology: topology describes the joint scoring/routing contract, not the number of auxiliary output series.

## Simple online models

### `mad_online`

Use for robust point anomalies on simple, non-seasonal, relatively stable metrics. It tolerates outliers and has very low operational cost, but does not explicitly model trend/calendar patterns.

### `zscore_online`

Use when the profile is stable/light-tailed and standard-deviation magnitude is meaningful. It is simple and explainable but more outlier-sensitive than MAD.

### `quantile_online`

Favor this specialized option when profiling shows negligible trend and a repeatable uneven or plateau-shaped seasonal distribution that benefits from explicit phase buckets, particularly a custom cycle: for example `seasonal_interval: 14d` with `min_subseason: 3h` (112 buckets per series). Uneven means recurring phase shape, not irregular timestamps. Require adequate observations and repeated cycles in each bucket; one cycle alone does not demonstrate repeatability.

For other non-trivial temporal profiles, prefer Temporal Envelope, including changing levels, trend and calendar effects. MAD/z-score remain appropriate for simple stationary data. Envelope may use less state and fit/infer faster than a fine-bucket seasonal quantile model, but this is a workload-dependent expectation: check sizing and representative timing before claiming savings. Do not map a 14-day cycle to weekly DOW or assume envelope supports every custom period. Respect explicit user choices and retain a quantile model when measured quality justifies it.

For stable MAD, Z-score, and online-quantile distributions, use `history_strength > 1` (typically `2`–`3`) to reduce the leverage of new observations without fitting many extra historical cycles. This can reduce fit-time data, CPU, and RAM, but it does not replace coverage of every required seasonal phase and should not anchor a genuinely changing regime.

## Legacy offline models

Do not include offline models in the ordinary candidate set for new configurations or use one as a fallback when the profile is uncertain. Prefer the corresponding online model. Mention an offline model only when auditing an existing legacy configuration, when the user explicitly asks for it, or when a controlled comparison has already shown a material requirement the online model does not meet.

### `prophet`

Temporal Envelope covers the preferred online trend, calendar, holiday, shift, and forecast workflow. Keep Prophet only for an existing legacy configuration or when the user explicitly requests it and validation establishes a material benefit.

### `holtwinters`

Keep Holt-Winters only for an existing legacy configuration or an explicit, validated requirement.

### Isolation Forest

Isolation Forest requires periodic refitting and does not extrapolate a temporal forecast. Keep it only for an existing legacy configuration or an explicit, validated feature-space requirement; use Temporal Envelope Multivariate for the normal cross-channel recommendation path.

## Fit-window and cadence guidance

| Profile | Minimum history | Preferred starting history |
|---|---:|---:|
| HOD/daily | `2d` | `7d` |
| DOW/weekly | `2w` | `30d` |
| month-of-year | `24mo` when feasible | `24mo+` |

Use the longest required history for multiple profiles. Explain when available history is shorter. Partial fit history can still be useful for online models, but cold-start/warmup remains visible.

For online models, prefer a deliberate long `fit_every`, such as `1000w`, when periodic rebuilding is not intended. This is not true fit-once scheduling: startup/restore and eventual refits still apply. Offline models need a suitable regular refit interval.

For online MAD, z-score and quantile with long refit intervals, prefer `0 < decay < 1` when drift adaptation is intended. `decay: 1` keeps historical weight; reserve it for a deliberate cumulative baseline. Choose an adaptation horizon and check actual update semantics: z-score weights individual samples, digest-based models can decay per update batch, and seasonal buckets update only in their own phases. Do not translate decay directly from inference cadence or reuse one coefficient for every model. Faster forgetting can absorb sustained anomalies; balance it with warmup and `history_strength`. Peer models additionally constrain effective-sample warmup. Use schema-supported history/window controls for rolling and temporal-envelope models rather than adding an unsupported generic `decay`. Validate the installed model schema and preserve explicit user choices.

## Autotune guidance

- Autotune a selected model; v1.30 shared autotune does not choose a class.
- `anomaly_percentage` is an upper detection-volume constraint, not a target count.
- Use `exact:true` for online validation to match causal production inference.
- Keep business facts frozen: known direction, data bounds, holidays, `groupby`, and mandatory thresholds.
- Optimize complexity when comparable candidates exist so simpler fitted state wins ties.
- Apply and validate returned `result_data.data.modelConfig`.
- Deploy `class: auto` only when refit-time retuning is explicitly desired.

For new online deployments, recommend an explicit inactive-model retention policy (initially `settings.retention: {ttl: 1w, check_interval: 5m}`), keeping `check_interval` below `ttl` and every scheduler’s `fit_every` (reduce 5m for refits at 5m or less) and preserving valid user choices. Adjust for churn and intermittent entities; TTL evicts stale instances and is independent of decay. Pair restoration with provisioned durable model/data storage; `restore_state: true` alone cannot provide persistence. See the preset completion guide for deployment choices.
