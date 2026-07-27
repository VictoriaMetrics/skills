# vmanomaly review and evaluation reference

This guide defines consistent evidence and avoids overstating unlabeled results.

## Contents

- [Evidence levels](#evidence-levels)
- [Static checks](#static-checks)
- [Model-data fit](#model-data-fit)
- [Detection evaluation](#detection-evaluation)
- [Common failure patterns](#common-failure-patterns)
- [Report template](#report-template)

## Evidence levels

1. **Runtime fact:** health, build info, compatibility response, live schema, validation error.
2. **Measured profile:** characteristics over a stated query/window/step/sample limit.
3. **Bounded experiment:** repeatable task result using stated model and interval.
4. **User-confirmed truth:** known incident, expected event, or reviewed detection.
5. **Hypothesis:** plausible explanation requiring another test.

Do not present levels 2–3 as labeled ground truth.

## Static checks

### Deployment readiness

- Online periodic models should restore compatible state from durable on-disk storage.
- High-churn inputs should use a retention TTL longer than legitimate series absence, with a check
  interval shorter than both TTL and the smallest `fit_every`.
- Hot reload should be content-polled, preceded by full-config validation, and covered by reload
  success metrics.
- Scatter inference only for many queries and measured synchronized load; match workers to actual
  CPU limits.
- Recommend sharding/replication only for measured capacity or availability requirements, and
  require output deduplication with replicated writers.

### Scheduler timing

- `infer_every` bounds how long a new point may wait for the next scheduled inference.
- `fit_window` must contain enough cycles for configured seasonality.
- `fit_every` controls refitting, not the online update cadence.
- A long `fit_every` is valid for an exploratory exact online task that should preserve one state;
  it is not a universal production recommendation.

Starting history guidance:

| Pattern | Minimum | Preferred |
|---|---:|---:|
| daily/HOD | `2d` | `7d` |
| weekly/DOW | `2w` | `30d` |
| month-of-year | `24mo` when feasible | `24mo+` |

Partial fit history can initialize online models, but warmup and weaker seasonal estimates should
be stated. Completely empty fit history requires causal cold-start and delays trusted scores.

### Cross references

- Every model query and scheduler alias resolves.
- Every model parameter exists in its exact class schema. Validate reader, scheduler, writer, and
  other top-level fields and cross-references with full-configuration validation.
- Multivariate groups contain aligned, semantically related channels.
- The writer can safely absorb requested output cardinality.

## Model-data fit

| Measured evidence | First candidate |
|---|---|
| simple, no strong trend/calendar pattern, robust baseline needed | `mad_online` |
| simple stable/light-tailed data | `zscore_online` |
| trend, several calendar profiles, holidays, or persistent shifts | `temporal_envelope` |
| normality is a changing relationship between aligned channels | `temporal_envelope_multivariate` |

When the profile is not demonstrably simple and stationary, start the comparison with Temporal
Envelope rather than treating an offline model as the fallback. Offline models are not first
candidates for new configurations. Review them only as legacy or explicitly requested choices,
and compare them with the corresponding online model.

Temporal Envelope profile names are shape hypotheses, not knobs to enable indiscriminately:

- smooth: gradual recurring curve;
- spiky: narrow recurring peaks;
- plateau: sustained phase levels.

Use the configured timezone for civil-time seasonality and DST correctness.

## Detection evaluation

### Unlabeled data

Report:

- detection rate = detected points / eligible scored points;
- count and duration of detection windows;
- labelsets affected and concentration across them;
- representative plots/windows;
- warmup and missing-data exclusions.

Do not call detections false positives until a human or labels establish they are normal.

### Labeled or user-confirmed data

Report metrics appropriate to the event:

- precision, recall, and F1 for detection utility;
- detection delay for persistent changes;
- time to stable and settled-regime false-positive rate for adaptation;
- forecast/boundary error only for models that produce those outputs.

Evaluate online models causally. Batch inference can leak future observations into validation and
select parameters that underperform in production exact inference.

### Comparison discipline

Keep query, step, timezone, fit/inference windows, direction, business thresholds, and labels fixed.
Change one coherent configuration at a time. Record task/model specifications with results.

## Common failure patterns

| Symptom | Check first | Possible response |
|---|---|---|
| many early detections | warmup, fit coverage, missing prior history | raise justified warmup or extend history |
| recurring false-looking peaks | wrong/missing calendar profile, event contamination | correct profile; use robust Temporal Envelope |
| persistent detections after shift | changepoint confirmation and trend reactivity | test window/reactivity, preserve anomaly-burst resistance |
| misses small meaningful changes | business deadbands, interval width, direction | correct units; tune justified fields |
| high detection volume everywhere | wrong data range, narrow boundaries, mismatched model | fix domain values; compare simpler/better-fit class |
| multivariate score dominated by noise | grouping, channel semantics, aggregation | regroup, reduce channels, compare `l2`/`mean` |
| UI task appears empty | datasource interval, fit history, warmup, output selection | inspect task error/result; do not assume model failure |
| upgrade fails to load state | compatibility response | follow scoped purge guidance with approval |

## Report template

```markdown
## Summary
- Runtime/version:
- Compatibility:
- Scope and query window:
- Overall verdict:

## Findings
### <severity>: <title>
- Evidence:
- Impact:
- Proposed minimal change:
- Verification:

## Per-model results
| Model/query | Profile fit | Detection evidence | Verdict |
|---|---|---|---|

## Assumptions and follow-up
- ...
```
