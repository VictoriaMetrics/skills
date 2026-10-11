# Initial recipes

Recipes are query-construction hints, not pre-approved production expressions. Discover exact labels and units, constrain selectors to the customer's scope, execute the query and inspect coverage before tuning. Keep requested grouping labels through aggregation.

| Domain | Candidate | Construction and guardrails |
| --- | --- | --- |
| node-exporter | CPU busy fraction | Derive from `rate(node_cpu_seconds_total{mode="idle", ...}[5m])`; aggregate CPU cores within the host, then subtract from 1. Preserve tenant/cluster/job/instance identity. Bounded 0–1; consider upper temporal deviations and a separate hard saturation rule. |
| node-exporter | Context switches | `rate(node_context_switches_total{...}[5m])`; per-host temporal baseline, both directions only when operationally relevant. Counter resets must not become artificial spikes. |
| node-exporter | Disk availability | Available/size ratio with matching filesystem identity; exclude irrelevant pseudo-filesystems only after discovery. Prefer a static capacity rule; no universal threshold is imposed. |
| VictoriaMetrics | Ingestion | Rate of the discovered rows-added/inserted counter, grouped by relevant component/tenant. Verify replication and component semantics before summing; drops and unexpected growth have different business meanings. |
| VictoriaMetrics | Query workload | Discover request counters and duration histograms. Verify bucket units and minimum traffic before constructing rate/quantile queries. Do not interpret absent buckets as zero latency. |

Use peer detection only for comparable hosts/components and a supported complete pool; role, capacity and workload differences can invalidate the cohort. Keep a temporal detector where fleet-wide degradation matters. Use joint models only for a meaningful relationship, aligned channels and complete groups, not merely because several queries exist.

Kubernetes and Kafka discovery is supported as metadata exploration, but this initial recipe set does not promise validated domain bundles for every exporter/version. Report unknown families without inventing names. Static rules adapted from third parties must retain the source revision, attribution, applicable license link and modification notice; validate the actual rule against the selected workload.
