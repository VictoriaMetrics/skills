---
name: vmanomaly-sizing
description: >
  Estimate vmanomaly deployment CPU, RAM and disk for a known workload, or approximate inference capacity for fixed resources. Use for deployment sizing, maximum active time-series questions, RAM-versus-disk comparisons, or suspected OOM during fitting. Not for forecasting a monitored metric's capacity or selecting anomaly models.
allowed-tools: Bash(curl:*), Bash(jq:*), Read
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

- One univariate model usually serves one series; multivariate counts refer to groups and also need channels per group. Do not assume support for peer-group or autotune-wrapper sizing.
- Keep history depth, sampling step, inference window and inference cadence separate. For non-overlapping cycles, new points follow cadence/step; an explicit window or overlapping batch needs an explicit point count. Verify the resolved request.
- Online models default to bootstrap-only fitting. Omit `fit_every_seconds` unless periodic refits were explicitly requested; never copy `fit_window` into it. Bare MAD/Z-score names resolve to their online equivalents. A long bootstrap is advisory, but its RAM/disk requirements still count in forward sizing. Reverse sizing excludes bootstrap, refits and churn work.
- For equal query shards of the same model, pass total `entity_count`, `query_count`, and explicit deployment membership with `split_by: queries`. If only the query count is proposed, disclose any one-member-per-query assumption. More instances do not automatically subdivide fixed queries. Preserve explicit placement after an infeasible result.
- Compare CPU candidates in one forward call. Keep RAM/disk comparisons otherwise identical. `storage_mode` accepts `memory` or `disk`; it is a sizing option, not a deployment YAML field. Persistent state restoration has separate storage requirements.

## Direct API examples

Requires Bash, jq and [curl 7.76.0+](https://curl.se/docs/manpage.html#--fail-with-body) for `--fail-with-body` and stderr write-out. Check `curl --version`; use an available MCP tool or a compatible curl installation if the client is older.

Use the user's configured server and authentication. `VM_ANOMALY_URL` must include any path prefix. `VM_CURL_CONFIG` points to an existing protected curl configuration, or `/dev/null` for an unauthenticated instance. Do not print credentials or create a credential file. Do not use automatic retries. The examples keep the JSON body on stdout, expose response headers (including `Retry-After`) and HTTP status on stderr, and preserve a nonzero exit status on failure.

Forward example: 100,000 MAD series, one week of one-minute history, two-minute inference with two new points, disk storage:

```bash
set -o pipefail
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --max-time 30 --fail-with-body \
  --dump-header /dev/stderr --write-out '%{stderr}HTTP status: %{http_code}\n' \
  -H 'Content-Type: application/json' \
  "$VM_ANOMALY_URL/api/v1/deployment-sizing/estimate" \
  --data '{"workloads":[{"model_class":"mad_online","entity_count":100000,"infer_every_seconds":120,"infer_points_per_cycle":2,"fit":{"window_seconds":604800,"step_seconds":60}}],"policy":{"storage_mode":"disk"}}' | jq .
```

Reverse example: the same history/cadence, eight CPUs and a six-GiB RAM limit:

```bash
set -o pipefail
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -sS --max-time 30 --fail-with-body \
  --dump-header /dev/stderr --write-out '%{stderr}HTTP status: %{http_code}\n' \
  -H 'Content-Type: application/json' \
  "$VM_ANOMALY_URL/api/v1/deployment-sizing/throughput" \
  --data '{"model_class":"mad_online","cpus":8,"ram_limit_bytes":6442450944,"infer_every_seconds":120,"infer_points_per_cycle":2,"history":{"window_seconds":604800,"step_seconds":60},"storage_mode":"disk"}' | jq .
```

MCP wraps optional fields differently: forward workload `fit`/`query_count` belong in each workload's `options`, while `policy`/`deployment` belong in top-level `options`. Reverse `history`/`storage_mode` belong in top-level `options`; `ram_limit_bytes` stays a named argument. Follow the discovered tool schema rather than sending an HTTP body unchanged to MCP.

## Interpret and recover

Report per-instance versus fleet totals, planned RAM/disk, inference time against cadence, limiting constraints, bootstrap duration and omitted costs. Keep nominal time distinct from time with headroom. Storage includes both input data and model state; do not call the whole disk estimate model dumps. `search_limit_reached: true` is a lower bound at the search ceiling, not a demonstrated maximum. The estimate is not a measured guarantee or an OOM bound. Use one short caveat: “Experimental estimate; validate with a representative workload.” Omit calibration coefficients, benchmark dimensions, extrapolation factors and implementation details from user-facing prose.

On 422, report actionable missing/invalid fields or binding constraints. Correct a configuration error only when the intended value is known; ask for missing choices. Unsupported seasonal configurations need a matching profile or offline calibration, not a smaller fleet. Do not silently change a fixed topology, deadline or workload to obtain a feasible answer. On overload, stop immediate retries and respect `Retry-After` when supplied. An unavailable route means this server cannot provide the estimate.

For suspected OOM, check container termination reasons and memory events; CrashLoopBackOff alone is not proof. If resource pressure is confirmed, compare disk-backed storage, shorter justified history or fewer input series, then worker/batch limits and sharding. Distinguish bootstrap peaks from steady inference and active models from retained inactive state. Present proposed changes for review; estimates do not deploy them.
