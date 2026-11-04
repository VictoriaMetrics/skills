# Preset workflow guide v1

Discover, evaluate, size and generate matching files or report blockers. Workspace edits are not completion; generation never authorizes deployment.

## Scope and budgets

Preserve authorized datasource/tenant/scope and preferences, including explicit multitenant routes. Never enumerate tenants or broaden scope. Inspect live schemas; unsupported capabilities are not empty data. Do not alter cadence/history/topology/workload to make sizing succeed.

Per initial preset request: at most 10 metadata calls (100 items each, initially one day), five profiling calls including retries, two sequential autotune studies and ten status calls per task. Profile with explicit `limit: 5`, `verbose: false` and fixed start/end/step; bound points by window/step too. Reuse evidence, report sampling and stop on overload/timeouts rather than automatically retrying. Copilot may enforce these budgets; elsewhere they are instructions, not TSDB scan-cost guarantees. Preserve room for file generation and disclose incomplete analysis.

## Discover and select

1. Use `vmanomaly_discover_metrics`: metric names, then label names/values and bounded series inspection as needed. Prefixes are hints, not proof of semantics. Preserve warnings/completeness; sampled lists do not establish fleet cardinality.
2. Select a small actionable signal set from existing metrics and labels. For node-exporter, consider CPU, available-memory ratios, filesystem capacity and disk/network rates. Convert counters to rates; verify units and device/filesystem exclusions. Preserve host identity unless the user chooses aggregation, explaining that it can hide failing hosts. Keep deterministic/static checks separate from ML.
3. Execute candidate expressions, inspect samples/history and obtain time-series characteristics. List installed models and retrieve relevant schemas. Use multivariate models for aligned related signals and peer models for comparable complete groups, not merely because multiple metrics exist.
4. Set guardrails from user intent and evidence; disclose tentative choices. Inference ordinarily starts at 5m; select query sampling separately to preserve relevant events. Preserve explicit cadence and explain overly coarse choices. Schema validity does not establish detection quality.

Consult the [model-selection guide](https://docs.victoriametrics.com/anomaly-detection/guides/model-selection/), linked rather than bundled. For installed docs use `vmanomaly_search_docs` then `vmanomaly_read_doc_section` with returned URI/offsets. External links require browsing; live schemas take precedence.

Prefer online MAD/z-score for simple stationary signals and Temporal Envelope for other non-trivial temporal profiles. Favor `quantile_online` for negligible-trend, repeatable uneven/plateau phases benefiting from explicit buckets: e.g. `seasonal_interval: 14d`, `min_subseason: 3h` gives 112 buckets per series. Uneven means recurring phase shape, not irregular sampling. Verify repeated cycles and observations per bucket; weekly DOW is not a 14-day cycle, and envelope need not support arbitrary periods. Envelope may use less state and fit/infer faster than fine-bucket quantile, but verify workload-specific costs. Preserve explicit choices and demonstrated quality advantages.

## Evaluate quality

Inspect training/evaluation coverage, gaps and level changes. Explain window changes; never bridge long gaps or discard incidents to improve scores. Digest decay advances on updates, not elapsed missing time.

Run bounded autotune unless declined, already evaluated or unsupported; disclose skips and untuned groups. Use a provisional `anomaly_percentage: 0.02` (2% anomalous points), not a false-positive guarantee or quota. Preserve query policies. For online models: `limit: 5`, `optimization_params: {n_trials: 32, timeout: 8, exact: true, n_jobs: 1}`; at most two sequential studies.

Prefer supported `replay` with production `fit_window`, `fit_every`, `infer_every`, fixed start/end and sampling step; verify returned replay metadata. Replay overrides fold settings and requires preceding training history. Otherwise use regular folds and disclose cadence mismatch. Never bypass missing history with leaky one-fold in-sample scoring.

Create via `vmanomaly_create_autotune_task`; retrieve status sequentially with `vmanomaly_get_autotune_task`, preferring supported `wait_seconds: 10`, otherwise waiting 2–5s. Stop after ten polls, retain task IDs, and never recreate running/failed tasks or use unfinished results.

Compare tuned and untuned candidates on later observations excluded from tuning, using replay or separate detection tasks (`exact` alone does not reproduce schedules). Check baseline, per-series/aggregate anomaly fractions and streaks; keep joint/peer groups intact. Revisit history/model choice before widening thresholds; do not conceal sustained changes to meet a target. Prefer simpler candidates when tuning adds no benefit. Carry selected parameters into the bundle and disclose unverified quality.

## Size and configure

Estimate resources for actual or explicitly estimated production output-series counts, topology, sampling, inference cadence and history. Metadata sample counts are lower bounds, not fleet size. Preserve headroom and explain assumptions; small-sample estimates do not show that memory barely grows with fleet size.

Build a complete reader/writer/model/query/scheduler config. Every active periodic scheduler needs explicit non-null `fit_every`: omission inherits `infer_every` and can repeatedly refit full history. For continuously updating online models, a deliberate long interval such as `1000w` avoids routine rebuilding; it is not true fit-once behavior, and startup/restore still applies. Batch models need regular refits. Use separate schedulers where needed and identical cadence assumptions in sizing.

Prefer supported short aliases (`vm`, `periodic`, `mad_online`); omit unneeded defaults but retain intentional zero/false/null values, user aliases and query policies. Reuse destinations only when their role is known: a reader URL is not automatically a score writer. Use secret references, never invented credentials.

Choose forgetting explicitly for long refit intervals. MAD/z-score/quantile usually need `0 < decay < 1` for drift; use `1` only for a deliberate cumulative, slower-adapting baseline. Derive decay from the desired horizon and documented update semantics, not `fit_every`: z-score weights samples, digests may decay per batch, seasonal buckets only on matching phases. Disclose uncertain wall-clock mappings. Strong forgetting can normalize sustained anomalies. Check warmup and `history_strength` (not a forgetting substitute); peer warmup must fit the effective-sample limit at that decay. Rolling/envelope models use schema-supported history/window controls, not generic `decay`. Validate settings and preserve user choices.

## Drafts and complete artifacts

For preset recommendations, unknown writer details must not block drafts. Use `http://replace-me.invalid:8428` for an unknown writer URL; never probe or write to it. Request `required_inputs` accepts only `writer.datasource_url` and `writer.tenant_id`: mark only unresolved fields. Omit unknown writer tenants, never copy the reader tenant, and preserve explicitly supplied writer settings. Explain destination-specific cluster routing. Ask first if deployment-ready output was requested. A noop writer cannot produce score alerts. An unknown incident URL may be omitted with a warning.

Generate with `vmanomaly_generate_preset_artifacts`, complete config and alert policy. Preserve the entire returned `config_yaml`, `alerts_yaml` or replacement `files` list, including comments, warnings, validation/provenance, per-file requirements and `deployment_ready: false`. Response requirements (`field`/`instruction`) are distinct from writer-only request fields and may describe deployment prerequisites. Summarize unresolved items in chat. Never splice YAML, rewrite validated sections or mix generations; changed settings require regenerating the complete matching bundle. Use full-config validation separately only to diagnose intermediate configs. Fix correctable schema errors without changing user constraints; report unsupported fields/capabilities rather than dropping them.

Choose alert evaluation and persistence independently of sampling. Rule `for` measures sustained truth across evaluations, not independent model observations; 15m does not imply three observations or evaluations. `min_consecutive_points` is separate. Check score freshness and preserve source identity/incident annotations. Schema validity and empty checklists do not certify connectivity, history, quality, sizing, startup, alert delivery or deployment readiness.

Copilot renders download cards; never duplicate files via `display_yaml` or invent URLs. Other clients save returned strings. List files/remaining checks. Optional editor previews require user intent and the current revision; avoid no-ops and unsupported claims. Dashboard JSON needs separate assets.

## Deployment and state

Inspect the live artifact schema: pass `deployment` only when supported. Otherwise generate base files and use a separately supported adapter with its validated spec, or report deployment output unsupported. The bundled `scripts/render_bundle.py` does not implement storage selection or volume wiring.

If deployment/storage preferences are known, finish analysis/sizing and generate the complete bundle once, including base YAML; do not generate preliminary files merely for validation. Only when choices are missing, keep base config/alerts downloadable and ask one compact question: Compose, Helm or VM Operator; persistent state (recommended when durable storage exists) or ephemeral RAM? Reuse known answers. Generate alternatives only on request; regenerate complete bundles when choices arrive, inputs change or generation fails.

Pass `targets`, `storage` and a released `image` tag. Follow the schema for chart/Operator versions, namespace, license Secret, volume size, StorageClass and resources. Never invent classes/licenses, change storage modes or drop unsupported connection settings. For missing license/volume details, follow the adapter's omission rules and preserve backend-generated placeholders and per-file requirements. Report unknown capacity in chat; do not add deployment fields to request `required_inputs` or treat placeholder sizes as recommendations.

For Kubernetes, inspect pinned compatible [Helm values/schema](https://github.com/VictoriaMetrics/helm-charts/tree/master/charts/victoria-metrics-anomaly) or [Operator CRDs](https://docs.victoriametrics.com/operator/resources/vmanomaly/). Chart.yaml alone is insufficient. Fetch authorized assets at pinned revisions with provenance/checksums; validate whole staged bundles and preserve previous output on failure. Never patch running deployments as part of generation. Helm output is values plus pinned-chart instructions, not a fabricated chart archive; Operator output is a CR. Install alert rules separately in vmalert.

Persistent mode pairs `settings.restore_state: true` with writable durable model/data volumes. RAM pairs `restore_state: false` with no disk-mode environment variables. Preserve choices or clarify conflicts. Disk mode alone does not guarantee restart durability; size I/O, warmup, state and temporary fit data. Files remain drafts until secrets, storage and live checks are resolved; never claim deployment or live validation.

For new online presets recommend `settings.retention: {ttl: 1w, check_interval: 5m}` unless overridden; TTL is otherwise disabled by default. Keep checks below TTL and every scheduler's `fit_every`, reducing 5m for refits at 5m or less. TTL evicts stale model instances; decay forgets observations within active models. Include churn-retained models in sizing; discuss shorter TTL for high churn, longer TTL for intermittent entities, eviction cold starts, inference/refit constraints and joint/peer retention. Use supported model/scheduler overrides for differing lifetimes. TTL is neither a RAM/disk cap nor a promise to clean every file on the volume.
