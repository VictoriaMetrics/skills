---
name: vmanomaly-preset
description: Discover a bounded set of VictoriaMetrics signals and assemble an evidence-backed vmanomaly preset with configuration, alert rules, dashboards and a selected deployment form. Use when the user needs anomaly detection but does not yet know the queries. Use vmanomaly-config for known queries and vmanomaly-review for existing deployments.
allowed-tools: Bash(curl:*), Bash(jq:*), Bash(python3:*), Read
---

# Dynamic anomaly presets

Deliver a small, reproducible monitoring bundle. Start with the customer's authorized datasource/tenant, service scope, detection intent and deployment preference. Infer metric properties from data; ask only for business constraints or destinations that cannot be inferred. This workflow does not authorize deployment, remote dashboard updates or alert delivery.

For MCP/Copilot delivery, follow the [versioned preset completion guide](references/copilot-preset-guide-v1.md), the canonical source of the compact guide distributed by MCP. It defines file-generation completion, missing-destination handling and workspace-preview boundaries.

## Discover and choose

1. Check runtime tools and schemas. vmanomaly 1.31.0 sizing and MCP 0.5.0 are established capabilities; discovery and artifact generation require the newer endpoints described in [the API contract](references/api-contract.md). On 404, verify the server version and configured base URL, including any path prefix; only a confirmed missing endpoint means unsupported capability. Never interpret it as an empty inventory. If unavailable, use an already-configured VictoriaMetrics query tool within the same scope or deliver a clearly limited manual plan.
2. Set discovery budgets before calls: ordinarily at most 10 metadata requests, 100 items per call and one day of metadata, then profile at most five candidate queries. Broaden only with evidence and a stated cost. Track cumulative calls, returned items and incomplete responses; stop when the budget is reached. These are workflow defaults, not claims about TSDB scan cost.
3. Discover metric names through `__name__` values, then relevant label names/values. Metric prefixes are clues, not proof of semantics. Do not enumerate tenants. Read [recipes](references/recipes.md) for the selected domain; check every referenced metric and label before constructing a query.
4. Rank by user relevance, coverage, actionable interpretation, cost and existing alerts. Classify static, temporal, joint, peer or context-only. Keep counters as rates, normalize units, and avoid unsupported histogram assumptions. Missing metadata is unknown. Sample across entity groups rather than selecting only the first series.
5. For chosen exact queries, follow the available vmanomaly-config workflow or perform its equivalent: characteristics, live model schema, causal candidate evaluation and full-config validation at the same step/timezone. Prefer online models; preserve complete multivariate groups and comparable peer pools. Default inference to minute-scale cadence, ordinarily 5m, unless intent requires otherwise. Choose query step separately to retain relevant events and preserve existing query resolution. Choose explicit refit cadence as described in the completion guide; periodic `fit_every` otherwise inherits inference cadence.
6. Use existing deployment sizing for the actual topology and cardinality evidence. Sample counts are lower bounds, not exact fleet size. Keep unsupported configurations unsupported; do not substitute fewer peers, shorter history or a slower cadence to obtain a feasible estimate.

## Build and validate

For recommendation requests with unknown writer settings, generate a clearly labeled draft with a `.invalid` destination and structured required inputs as described in the completion guide. Never probe placeholders or silently reuse reader tenants. For deployment-ready requests, resolve writer settings first. Use explicit reader and writer URLs/tenants; vmalert must read the destination containing scores, which may differ from the input datasource. Use file/secret references, not inline credentials. Give model/scheduler aliases or the supported metric prefix deployment-specific identities when sharing an output tenant.

Generate configuration and alert rules with the artifact API. It owns runtime mappings and output labels. Preserve returned config/alert YAML intact, including comments and draft requirements; after any setting change regenerate and validate the complete matching pair rather than patching selected output sections. Supply the external incident URL and exact entity label names discovered from query results; no entity labels means a query-group investigation. Preserve the full joint query key. Use alert persistence deliberately; `for` is not a count of independent points.

Obtain the anomaly-score and self-monitoring dashboard JSON from an approved pinned source or the user's installation. Record their SHA-256 values and provenance. Do not fetch mutable latest assets or require access to a private repository. An available Grafana tool may supply existing JSON and datasource UIDs; publishing remains a separate authorized action.

Run `scripts/render_bundle.py` with the artifact response, deployment specification and two dashboard files. See [bundle inputs and checks](references/bundle-inputs.md). The helper uses Python's standard library, writes only to a new directory and performs no network operations. It preserves dashboard queries and adapts only supported variables and metadata. Custom output suffixes and arbitrary dashboard rewrites require manual adaptation.

Validate in layers and report each outcome: schema, query/history, sizing, deployment rendering, live startup, rule evaluation, incident navigation and dashboard queries. A generated or schema-valid bundle is not live-tested. If all selected signals are static, deliver static rules with provenance and explain that no vmanomaly deployment is needed; do not fabricate an ML workload.

## Handoff

Include selected and rejected queries with reasons, evidence window/step/timezone, topology, resource assumptions, exact artifact versions, unresolved inputs and validation results. Retain backend warnings. Document unknown history, empty groups, unsupported recipes and deployment checks still pending. Do not promise false-positive rates from unlabeled data or schedule ongoing reviews as part of this skill.
