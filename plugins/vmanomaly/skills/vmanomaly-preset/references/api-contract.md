# Optional discovery and artifact APIs

These additive capabilities are not part of the vmanomaly 1.31.0 / MCP 0.5.0 baseline. Discover the tools or check the endpoint before use; keep the existing sizing and tuning paths unchanged. New paths below are public HTTP contracts, not implementation dependencies.

`POST /api/v1/discovery` accepts `operation` (`metric_names`, `label_names`, `label_values`, `series`), `datasource_url`, optional `tenant_id`, nonempty `match` selectors, Unix `start`/`end`, `label` (required for `label_values`), `limit` (1–1000) and `timeout_seconds` (up to 30). The time window is bounded to 31 days. One call performs one upstream request. `vmanomaly_discover_metrics` exposes the same operation through MCP.

Preserve `items`, `returned_count`, `completeness`, `warnings`, resolved tenant and requested window. Completeness is `truncated` or `unknown`; do not infer total cardinality or exact historical coverage. Retry neither overload nor timeout automatically. Narrow the scope or report the limitation. Authentication follows the configured client; forward credentials only for the authorized datasource.

`POST /api/v1/preset/artifacts` accepts `{config, alerts}` and optionally `required_inputs` for draft generation. That list contains unresolved `writer.datasource_url` and/or `writer.tenant_id` fields; the config must still pass schema validation. `config` is the complete runtime configuration; `alerts` can specify `threshold`, `evaluation_seconds`, `persistence_seconds`, `incident_base_url` and `entity_labels`. `vmanomaly_generate_preset_artifacts` exposes the same operation. The response supplies `schema_version: 1`, normalized `config`, `alert_rules`, `config_yaml`, `alerts_yaml`, `validation: schema-valid` and `warnings`.

Draft-aware responses additionally supply `deployment_ready: false` and `required_inputs` objects containing `field` and `instruction`. A `.invalid` writer host is automatically marked unresolved. Both YAML strings carry draft/checklist comments when required inputs remain. An empty checklist does not certify connectivity or deployment readiness. Check tool schemas for this extension before using it.

The artifact API generates matching rules without applying configuration or probing destinations. Unsupported writer formats must fail explicitly. Preserve query-local guardrails and canonical output identities. Legacy exploration exports are not a substitute for a production writer.
