---
name: vm-trace-analyzer
description: >
  Analyze VictoriaMetrics query trace JSON output to diagnose query performance.
  Produces a structured report covering time breakdown, bottlenecks, data volume,
  and optimization recommendations. Works with both cluster (vmselect/vmstorage)
  and single-node deployments.
argument-hint: trace.json
disable-model-invocation: true
---

# VictoriaMetrics Query Trace Analyzer

Analyze a VictoriaMetrics query trace and produce a structured performance report.

## Background

VictoriaMetrics is a time series database. In cluster mode it has three components:
- **vmselect** — query frontend that accepts PromQL queries, fetches data from vmstorage nodes, and applies calculations
- **vmstorage** — stores time series data and serves it to vmselect over RPC
- **vminsert** — ingestion frontend (not involved in queries)

In single-node mode, all components run in one process, so there are no RPC calls, but the internal trace structure is similar.

Query tracing is enabled by adding `trace=1` to an HTTP query. The trace is a JSON tree where each node has:
```json
{
  "duration_msec": 123.456,
  "message": "description of what happened",
  "children": [ ... ]
}
```

The tree is rooted at vmselect. It captures the full query execution pipeline: parsing, series search, data fetch from storage, rollup computation, aggregation, and response generation.

## How to analyze

1. Read the trace JSON file the user provides
2. Walk the tree and identify the execution phases (see "Trace phases" below)
3. Build a time breakdown for each phase
4. Identify the bottleneck — the phase consuming the most wall-clock time
5. Produce the report (see "Report template" below)

For large traces, focus on the top-level children first. Drill into subtrees only when they are relevant to the bottleneck or when durations are surprising.

## Trace phases

A query trace typically has these phases, roughly in this order. Not all phases appear in every trace. Identify them by matching the message patterns described here.

### Phase 1: Query entry

The root node identifies the vmselect version, endpoint, query parameters, and result series count.

**Cluster pattern:** message starts with `vmselect-<version>: /select/...`
**Single-node pattern:** message starts with a version prefix and the endpoint path

Key fields to extract from the root message:
- Endpoint: `/api/v1/query` (instant) or `/api/v1/query_range` (range)
- `query=` — the PromQL expression
- `start=`, `end=`, `step=` — query time range parameters (for range queries)
- `series=` — total result series count

### Phase 2: Expression evaluation

Messages matching `eval: query=..., timeRange=..., step=..., mayCache=...: series=N, points=N, pointsPerSeries=N`

These trace the recursive evaluation of the PromQL expression tree. Each eval node may have children for sub-expressions. Key numbers:
- **series** — number of time series produced by this sub-expression
- **points** — total data points across all series
- **pointsPerSeries** — data points per series (= time range / step)

### Phase 3: Function and aggregation evaluation

- `transform <func>(): series=N` — PromQL functions (histogram_quantile, clamp, etc.)
- `aggregate <func>(): series=N` — aggregation operators (sum, avg, max, etc.)
- `binary op "<op>": series=N` — binary operations (+, -, >, etc.)

### Phase 4: Series search (index lookup)

This is where VictoriaMetrics resolves metric names and label matchers into internal series IDs.

**Cluster:** appears inside `rpc at vmstorage <addr>` → `rpc call search_v7()` → `vmstorage-<version>: rpc call search_v7() at vmstorage`
**Single-node:** appears directly without RPC wrappers

Key messages:
- `init series search: filters=..., timeRange=..., maxMetrics=N`
- `search TSIDs: filters=..., timeRange=..., maxMetrics=N`
- `search N indexDBs in parallel` — parallel index database search
- `search indexDB <name> (<type>): timeRange=...` — individual index partition
- `found N metric ids for filter=...` — metric ID resolution
- `found N TSIDs for N metricIDs` — TSID resolution
- `sort N TSIDs`

Cache-related messages in this phase:
- `search for metricIDs in tag filters cache` followed by `cache miss` or a cache hit (no "cache miss" child)
- `put N metricIDs in cache` / `stored N metricIDs into cache`

### Phase 5: Data fetch

**Cluster:** `fetch matching series: ...` wraps RPC calls to each vmstorage node
- `rpc at vmstorage <addr>` — per-node RPC
- `sent N blocks to vmselect` — amount of raw data transmitted back
- `fetch unique series=N, blocks=N, samples=N, bytes=N` — aggregate summary across all vmstorage nodes

**Single-node:** `search for parts with data for N series` followed by data scan messages

The **bytes** value in `fetch unique series` tells you total data transferred and is a good indicator of I/O load.

### Phase 6: Rollup computation

The rollup phase computes rate(), increase(), avg_over_time(), and similar range-vector functions.

Key messages:
- `rollup <func>(): timeRange=..., step=N, window=N` or `rollup <func>() with incremental aggregation <agg>() over N series`
- `the rollup evaluation needs an estimated N bytes of RAM for N series and N points per series (summary N points)` — memory estimate
- `parallel process of fetched data: series=N, samples=N` — the actual computation over raw samples
- `series after aggregation with <func>(): N; samplesScanned=N` — post-aggregation result

This phase often dominates execution time for queries that scan large amounts of raw data.

### Phase 7: Response generation

- `sort series by metric name and labels`
- `generate /api/v1/query_range response for series=N, points=N` or `generate /api/v1/query response for series=N`

Usually trivially fast.

## Report template

Produce the report in this format:

```
## Query Overview

- **Query:** `<the PromQL expression>`
- **Type:** instant / range query
- **Time range:** <start> to <end> (duration: <human readable>)
- **Step:** <step value in human-readable form>
- **Result:** <N> series, <N> points

## Performance Summary

- **Total duration:** <N>ms
- **Verdict:** <Fast / Acceptable / Slow / Very Slow>

Use these rough thresholds for the verdict:
  - Fast: < 500ms
  - Acceptable: 500ms–2s
  - Slow: 2s–10s
  - Very Slow: > 10s

## Execution Time Breakdown

| Phase | Duration | % of Total | Notes |
|-------|----------|------------|-------|
| Series search (index) | Xms | X% | |
| Data fetch | Xms | X% | |
| Rollup computation | Xms | X% | |
| Aggregation / functions | Xms | X% | |
| Response generation | Xms | X% | |

(Adapt the phases to what actually appears in the trace.
For cluster traces, break down data fetch per vmstorage node.)

## Data Volume

- **Matched series:** <N> (across all storage nodes)
- **Raw samples scanned:** <N>
- **Blocks fetched:** <N>
- **Bytes transferred:** <N> (human-readable, e.g., "268 MB")

## Storage Node Breakdown (cluster only)

| Node | Series | Blocks sent | Duration |
|------|--------|-------------|----------|
| vmstorage-1 | N | N | Xms |
| vmstorage-2 | N | N | Xms |

## Cache Analysis

Report tag filter cache hits/misses observed in the trace.
Note which index partitions had cache misses.

## Bottleneck Analysis

Identify the single biggest contributor to total query time.
Explain *why* it's slow in concrete terms (e.g., "scanning 212M raw samples
for the rollup computation takes 4.7s — this dominates the 5.7s total").

## Recommendations

Provide actionable suggestions to reduce query latency.
```

## Writing recommendations

Base recommendations on what the trace actually shows. Here are common patterns and the corresponding advice:

**High series cardinality (many matched series)**
- Suggest adding more specific label matchers to reduce series count
- Suggest using recording rules to pre-aggregate if this is a dashboard query

**Large raw sample scan (high samplesScanned)**
- Suggest increasing the query step to reduce points per series
- Suggest narrowing the time range
- For `rate()` over long ranges, suggest shorter `[window]` if semantically acceptable

**Slow index lookups (series search dominates)**
- Tag filter cache misses are normal on first query; note that repeated queries should be faster
- Large number of metric IDs per day partition suggests high churn or high cardinality metric
- Suggest more selective filters if possible

**Slow data fetch / high bytes transferred (cluster)**
- Large blocks/bytes suggests vmstorage is doing heavy I/O
- Multiple vmstorage nodes with very uneven durations may indicate hot spots or unbalanced sharding
- Suggest checking vmstorage disk I/O and network bandwidth

**Rollup computation dominates**
- Often caused by scanning millions of raw samples
- Suggest `step` increase, shorter time range, or recording rules
- Note if incremental aggregation is being used (good) or not (could be optimized by the query engine in newer versions)

**histogram_quantile with many buckets**
- High bucket cardinality (many `le` labels) multiplies series count
- Suggest reducing histogram bucket count at the instrumentation level if possible
- Suggest using recording rules to pre-compute quantiles

**Cache misses everywhere**
- First query after restart or for a new time range will always miss
- Suggest running the query again to verify cache-warmed performance
- If repeated queries still show misses, the cache may be too small

Do not speculate about issues that are not evidenced in the trace. If the trace looks healthy and the query is fast, say so.

## Additional guidance

- When reporting durations, use the `duration_msec` values directly from the trace. Do not estimate or calculate durations by subtraction unless explicitly noting it.
- In cluster traces, the same phases (index search, data scan) appear for each vmstorage node. Aggregate these for the summary but also show per-node breakdown so the user can spot imbalances.
- If the trace is too large to read in a single pass, read the top-level structure first, identify the slowest branches by `duration_msec`, and drill into those.
- Some traces may include `subquery` or `@ modifier` evaluation — treat these like nested eval phases.
- The `mayCache=false` field in eval messages indicates whether the result could be cached. This is informational, not an issue.
