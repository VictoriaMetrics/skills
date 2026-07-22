# vmanomaly deployment-readiness reference

Use this when a validated configuration will run continuously. Keep small deployments simple and
add operational controls only when their conditions apply. The official
[installation guide](https://docs.victoriametrics.com/anomaly-detection/quickstart/#how-to-install-and-run-vmanomaly)
links Docker, Docker Compose, Helm, and Operator deployment paths.

## Stateful online operation

For periodic online models, prefer one initial fit followed by causal inference updates. Protect
that accumulated state across restarts:

- set `settings.restore_state: true`;
- enable on-disk model and reader-data storage, which state restoration requires;
- mount the dump directories on durable storage rather than an ephemeral container filesystem;
- run the compatibility preflight before upgrades or changing persisted-state layout.

State reuse is exact only while model, query, and scheduler identity remains compatible. Parameter,
query, or sharding changes may invalidate or relocate some state and trigger a fresh fit.

## Retention and high churn

Configure [`settings.retention`](https://docs.victoriametrics.com/anomaly-detection/components/settings/#retention)
when labelsets appear and disappear, especially with online models or state restoration:

```yaml
settings:
  restore_state: true
  retention:
    ttl: 7d
    check_interval: 1h
```

Treat these values as an example, not a default:

- choose `ttl` longer than the longest legitimate absence of an active series; otherwise an
  intermittent but valid model may cold-start when it returns;
- use a shorter TTL for high-churn ephemeral labelsets and a longer one for intermittent business
  series;
- keep `check_interval < ttl` and below the smallest configured `fit_every`;
- if `ttl` exceeds an offline model's `fit_every`, refitting normally replaces its state before
  retention can clean it.

Retention removes stale model/training artifacts; it does not replace source-side metric retention
or output-series lifecycle policies.

## Configuration lifecycle

Use content-polled hot reload when configuration files or Kubernetes ConfigMaps are managed
externally:

- start with `--watch` and set `-configCheckInterval` only when the default check cadence is
  unsuitable;
- validate the full YAML before rollout;
- monitor `vmanomaly_config_last_reload_successful` and reload counters;
- combine hot reload with state restoration to reuse compatible state.

Do not promise zero model reinitialization: changing model parameters, queries, schedulers, or shard
assignment may require new state.

## Workload and resource controls

| Control | Recommend when | Avoid as a blanket default |
|---|---|---|
| `scheduler.scatter_infer_jobs: true` | many queries, short `infer_every`, `n_workers > 1`, synchronized bursts | one or a few cheap queries |
| `settings.n_workers > 1` | independent models/series and available CPU | tightly constrained single-core deployments |
| on-disk mode | model/data cardinality causes RAM pressure or state restoration is enabled | latency-sensitive small in-memory workloads, unless needed for restoration |
| query-range splitting | long fit reads hit memory, timeout, or datasource limits | bounded reads already complete reliably |
| `reader.series_processing_batch_size` tuning | measured processing memory/throughput bottleneck | changing the default without evidence |

Keep `infer_every` aligned with the required alert reaction time. Scattering smooths work within
that interval; it does not increase total capacity by itself.

## Scale-out and high availability

Introduce sharding only after one instance is resource-bound or when isolation is operationally
required. Add replication only for an explicit availability objective. Replicated writers require
VictoriaMetrics-side deduplication to avoid duplicate output samples. Hot reload can redistribute
sub-configurations between shards, reducing state-restoration reuse.

## Production handoff

Before presenting a configuration as deployment-ready, report:

- installation path and required persistent volumes/environment paths;
- state restoration and retention decisions;
- inference/refit cadence and expected reaction time;
- worker/scattering/on-disk choices with workload evidence;
- validation, compatibility, self-monitoring dashboard, and alert-rule status;
- upgrade, rollback, and cold-start assumptions.
