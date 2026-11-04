---
name: vmanomaly-sizing
description: >
  Estimate vmanomaly deployment CPU, RAM and disk for a known workload, or approximate inference capacity for fixed resources. Use for deployment sizing, maximum active time-series questions, RAM-versus-disk comparisons, or suspected OOM during fitting. Not for forecasting a monitored metric's capacity or selecting anomaly models.
allowed-tools: Bash(curl:*), Bash(jq:*), Bash(set -o pipefail), Read
---

# Deployment sizing

Currently experimental as of v1.31.0. Use the connected server's deployment-sizing API (v1.31.0+) or the corresponding MCP tools. Estimate vmanomaly resources without changing its configuration. No exact query, data fetch or autotune is needed when the model and workload shape are already known.

## Choose the unknown

| User knows | Estimate | MCP tool | HTTP route |
|---|---|---|---|
| Model, series count, inference cadence | Required resources | `vmanomaly_estimate_deployment_resources` | `POST /api/v1/deployment-sizing/estimate` |
| Model, CPUs, cadence; optionally RAM | Active models served per interval | `vmanomaly_estimate_inference_capacity` | `POST /api/v1/deployment-sizing/throughput` |
| Wants supported model configurations | Available sizing profiles | `vmanomaly_get_deployment_sizing_profiles` | `GET /api/v1/deployment-sizing/profiles` |

For reverse sizing, cardinality is the output: do not ask for a series count. Clarify missing history, sampling or model parameters when needed, or disclose defaults. Preserve an explicitly supplied version. Check model schemas or available profiles before supplying required parameters. Unsupported versions/configurations are not permission to substitute another model or seasonality.

## Preserve workload meaning

- One univariate model usually serves one series; multivariate counts refer to groups and also need channels per group. For peer-group models, use the pool-count semantics below on supporting servers. Size a tuned result using its concrete selected model and parameters, retaining its grouping. The estimate excludes the `auto` wrapper's optimization search; do not present it as the wrapper's total resource requirement.
- Keep history depth, sampling step, inference window and inference cadence separate. For non-overlapping cycles, new points follow cadence/step; an explicit window or overlapping batch needs an explicit point count. Verify the resolved request.
- Online models default to bootstrap-only fitting. Omit `fit_every_seconds` unless periodic refits were explicitly requested; never copy `fit_window` into it. Bare MAD/Z-score names resolve to their online equivalents. A long bootstrap is advisory, but its RAM/disk requirements still count in forward sizing. Reverse sizing excludes bootstrap, refits and churn work.
- For equal query shards of the same model, pass total `entity_count`, `query_count`, and explicit deployment membership with `split_by: queries`. If only the query count is proposed, disclose any one-member-per-query assumption. More instances do not automatically subdivide fixed queries. Preserve explicit placement after an infeasible result.
- Compare CPU candidates in one forward call. Keep RAM/disk comparisons otherwise identical. `storage_mode` accepts `memory` or `disk`; it is a sizing option, not a deployment YAML field. Persistent state restoration has separate storage requirements.

## Peer-group sizing

On servers supporting experimental `peer_outlier` sizing, use `topology: wide` and `channels_per_entity` for peers per pool. Forward `entity_count` counts pools, not individual peers; model state is per pool and outputs are per peer. Reverse sizing takes a pool width, CPUs and cadence (optionally RAM), not a pool count or `workloads`; report the returned pool-model capacity and `input_series` separately. Separate reverse scenarios for different widths are not additive capacities on the same hardware.

Keep the full requested pool width: the 64-peer calibration sample is not a workload cap. The current estimator accepts equal-size fixed pools of 3–10,000 peers, complete observations and no churn retention. `model_params.min_peer_count` defaults to 5; for a 3- or 4-peer pool, explicitly set it to 3 or 4 respectively. This parameter must not exceed the pool width and is limited to 3–64 by the current estimator; higher minimums require offline calibration. A 10,000-peer pool can use the default minimum of 5. For forward sizing, use one query per workload and separate workloads for different queries or pool sizes; do not average unequal pools. Omit `model_params.groupby`: the declared pools are already grouped. A missing shipped peer profile does not itself mean unsupported; the installed server version can use bounded live calibration. An older server's rejection is not permission to substitute univariate models or fewer peers.

For example, 100 pools of 100 peers means 100 model states and 10,000 input series. This forward HTTP body preserves one-minute inference and sampling, one week of initial training and disk storage; omit `fit_every_seconds` for bootstrap-only fitting:

```json
{"workloads":[{"model_class":"peer_outlier","topology":"wide","entity_count":100,"channels_per_entity":100,"infer_every_seconds":60,"infer_points_per_cycle":1,"fit":{"window_seconds":604800,"step_seconds":60}}],"policy":{"storage_mode":"disk"}}
```

Use the server's estimate rather than calculating resource numbers locally. Peer estimates are less calibrated than regular profiles: show the returned `estimate_notice` once, or “Rough peer-group estimate; allow extra headroom and validate with your workload.” Keep operational limits and omitted costs visible without explaining calibration formulas.

## Direct API examples

Requires Bash, jq and [curl 7.84.0+](https://curl.se/docs/manpage.html#--write-out) for selective response-header write-out and `--fail-with-body`. Check `curl --version`; use an available MCP tool or a compatible curl installation if the client is older.

Use the user's configured server and authentication. `VM_ANOMALY_URL` must include any path prefix. `VM_CURL_CONFIG` points to an existing protected curl configuration, or `/dev/null` for an unauthenticated instance. Do not print credentials or create a credential file. Do not use automatic retries. The examples keep the JSON body on stdout, expose only HTTP status and `Retry-After` on stderr, and preserve a nonzero exit status on failure. Do not enable verbose tracing or dump all headers: responses can contain session cookies.

Forward example: 100,000 MAD series, one week of one-minute history, two-minute inference with two new points, disk storage:

```bash
set -o pipefail
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --max-time 30 --fail-with-body \
  --write-out '%{stderr}HTTP status: %{http_code}\nRetry-After: %header{retry-after}\n' \
  -H 'Content-Type: application/json' \
  "$VM_ANOMALY_URL/api/v1/deployment-sizing/estimate" \
  --data '{"workloads":[{"model_class":"mad_online","entity_count":100000,"infer_every_seconds":120,"infer_points_per_cycle":2,"fit":{"window_seconds":604800,"step_seconds":60}}],"policy":{"storage_mode":"disk"}}' | jq .
```

Reverse example: the same history/cadence, eight CPUs and a six-GiB RAM limit:

```bash
set -o pipefail
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --max-time 30 --fail-with-body \
  --write-out '%{stderr}HTTP status: %{http_code}\nRetry-After: %header{retry-after}\n' \
  -H 'Content-Type: application/json' \
  "$VM_ANOMALY_URL/api/v1/deployment-sizing/throughput" \
  --data '{"model_class":"mad_online","cpus":8,"ram_limit_bytes":6442450944,"infer_every_seconds":120,"infer_points_per_cycle":2,"history":{"window_seconds":604800,"step_seconds":60},"storage_mode":"disk"}' | jq .
```

MCP wraps optional fields differently: forward workload `fit`/`query_count`/`topology`/`channels_per_entity` belong in each workload's `options`, while `policy`/`deployment` belong in top-level `options`. Reverse `history`/`storage_mode`/`topology`/`channels_per_entity` belong in top-level `options`; `ram_limit_bytes` stays a named argument. Follow the discovered tool schema rather than sending an HTTP body unchanged to MCP.

## Interpret and recover

Report per-instance versus fleet totals, planned RAM/disk, inference time against cadence, limiting constraints, bootstrap duration and omitted costs. Keep nominal time distinct from time with headroom. Storage includes both input data and model state; do not call the whole disk estimate model dumps. `search_limit_reached: true` is a lower bound at the search ceiling, not a demonstrated maximum. The estimate is not a measured guarantee or an OOM bound. Use the returned `estimate_notice` once; without one use the peer caveat above for peer models, otherwise “Experimental estimate; validate with a representative workload.” Omit calibration coefficients, benchmark dimensions, extrapolation factors and implementation details from user-facing prose.

On 422, report actionable missing/invalid fields or binding constraints. Correct a configuration error only when the intended value is known; ask for missing choices. Unsupported seasonal configurations need a matching profile or offline calibration, not a smaller fleet. Do not silently change a fixed topology, deadline or workload to obtain a feasible answer. On overload, stop immediate retries and respect `Retry-After` when supplied. On 404, verify the configured base URL (including its path prefix) and server version before concluding that the sizing API is unavailable. Correct a confirmed URL error; if the intended base URL is unknown, ask rather than probing guessed paths.

For suspected OOM, check container termination reasons and memory events; CrashLoopBackOff alone is not proof. If resource pressure is confirmed, compare disk-backed storage, shorter justified history or fewer input series, then worker/batch limits and sharding. Distinguish bootstrap peaks from steady inference and active models from retained inactive state. Present proposed changes for review; estimates do not deploy them.
