# Bundle inputs and validation

Run from the installed skill directory:

```sh
python3 scripts/render_bundle.py --artifacts artifacts.json --spec deployment.json --anomaly-dashboard anomaly.json --monitoring-dashboard monitoring.json --output new-bundle
```

The output directory must not exist. Files with `.yaml` extensions contain JSON, a YAML 1.2 subset; expressions are serialized, never interpolated through a shell. The helper requires no third-party Python packages and never deploys or downloads anything.

Common deployment specification fields:

```json
{
  "name": "node-health",
  "deployment": "compose",
  "vmanomaly_image": "victoriametrics/vmanomaly:<supported-version>",
  "vmalert_image": "victoriametrics/vmalert:<supported-version>",
  "score_datasource_url": "https://scores.example.com",
  "notifier_url": "https://alertmanager.example.com",
  "anomaly_datasource_uid": "metrics",
  "monitoring_datasource_uid": "self-monitoring",
  "dashboard_sha256": {"anomaly": "<sha256>", "monitoring": "<sha256>"},
  "dashboard_sources": {"anomaly": "<pinned-source>", "monitoring": "<pinned-source>"}
}
```

Replace placeholders with verified versions and destinations. For Helm add `chart_version`, `license_secret`, optional `license_secret_key` and measured `resources`. For Operator add `operator_version`, `namespace`, `license_secret`, optional `license_secret_key`, measured `resources` and `rule_labels` matching the intended VMAlert selector. Image tags must be explicit and verified against the chosen registry; a tag is not proof of immutable content. Use a digest for Compose when immutability is required. This first Kubernetes renderer does not support digest-form images.

Compose expects `VMANOMALY_LICENSE_FILE` to reference an existing local license file. Configure additional authentication/TLS mounts, durable state paths and reachable service/UI addresses before live validation. Helm emits vmanomaly chart values plus separate rule/dashboard files; it does not assume the customer has installed a particular vmalert chart. Operator emits VMAnomaly and VMRule; it does not install an operator, VMAlert or Grafana.

The initial renderers target one instance and preserve complete groups. HA, automatic sharding, arbitrary secret-mount synthesis, custom writer suffixes and dashboard query rewriting are intentionally excluded. Declare required prediction outputs before generating artifacts; the helper does not silently change model outputs to fill an empty panel.

Validate Compose with `docker compose config`, Helm with lint/template against the pinned chart, and Operator resources against the pinned CRDs followed by a disposable reconciliation check. Extract and validate the resulting vmanomaly config where rendering/reconciliation transforms it. Check alert templates with vmalert, then evaluate score freshness/persistence on fixture data. Query dashboard expressions against fixture outputs and inspect datasource switching and incident links in the browser. Record pass/fail/skipped per layer; the manifest starts with pending checks and never marks a deployment live-tested automatically.

An all-static plan does not use this ML bundle helper. Deliver validated static rules, dashboard context and source/license provenance separately.
