---
name: vm-trace-analyzer
description: >
  Analyze VictoriaMetrics query trace JSON to diagnose slow queries and produce
  a structured performance report with time breakdown, bottleneck analysis, and
  optimization recommendations. ALWAYS use this skill when:
  (1) the user mentions a VictoriaMetrics or VM trace, query trace, or trace JSON,
  (2) the user provides or references a JSON file containing duration_msec/message/children fields,
  (3) the user asks why a VictoriaMetrics/VM query is slow and has trace output,
  (4) the user asks about vmstorage node distribution, cache misses, or rollup performance
  in the context of a trace,
  (5) the user mentions vmselect trace, trace=1, or query performance debugging with
  VictoriaMetrics. This skill provides a structured report template that ensures consistent,
  thorough analysis — do not attempt to analyze VM traces without it.
argument-hint: trace.json
disable-model-invocation: true
---

# VictoriaMetrics Query Trace Analyzer

You are analyzing a VictoriaMetrics query trace — a JSON tree that records every step of a PromQL query execution. Your goal is to read this tree, understand what happened, and produce a clear performance report with actionable recommendations.

## Background

In **Cluster** mode two components are involved in query processing:
- **vmselect** — query frontend that accepts PromQL or MetricsQL queries, fetches data from vmstorage nodes, and applies calculations
- **vmstorage** — stores time series data and serves it to vmselect over RPC

**Single-node** mode runs everything in one process. The trace structure is similar but without RPC wrappers.

You can tell which mode you're looking at from the root message in trace:
- **Cluster** traces contains `vmselect-<version>: /select/...`,
- **Single-node** traces contains `/victoria-metrics-<version>: /api/v1/...`.

## What is a query trace?

When you add `trace=1` to a VictoriaMetrics HTTP query, it returns a JSON tree describing every internal operation.
Each node looks like this:

```json
{
  "duration_msec": 123.456,
  "message": "description of what happened",
  "children": [ ... ]
}
```

The tree is rooted at vmselect. It captures the full query execution pipeline: parsing, series search, data fetch from storage, rollup computation, aggregation, and response generation.

## How to analyze the trace

### Step 0: Run the parse script

Before manually reading the trace file, run the analysis script to extract structured data:

```bash
python3 <skill_base_dir>/scripts/parse_trace.py <trace_file>
```

This outputs: root info, trace tree (depth 3), key nodes with durations, per-vmstorage RPC breakdown, and computed totals (bytes, samples, series). Use this output as your primary data source for the report.

Additional subcommands for deeper investigation:
- `python3 <script> <trace> tree --depth N` — print the trace tree to depth N
- `python3 <script> <trace> nodes --pattern "fetch unique"` — find all nodes matching a substring

Only drill deeper if the summary output reveals ambiguities or missing information.

After running the summary, also check for relevant performance improvements in newer VictoriaMetrics versions:

```bash
python3 <skill_base_dir>/scripts/check_changelog.py <version> <mode>
```

Where `<version>` is the semver from the parse script output (e.g., `v1.130.0`) and `<mode>` is `cluster` or `single-node`. This fetches changelogs from GitHub and shows performance-relevant fixes/features in versions newer than what the trace was captured on. If the fetch fails, skip this section gracefully.

### Step 1: Start at the root

Read the trace JSON file the user provides (or use the script output from Step 0).
The root node tells you the big picture. Extract:
- **Endpoint**: `/api/v1/query` (instant) or `/api/v1/query_range` (range)
- **Query**: the PromQL expression after `query=`
- **Time parameters**: `start=`, `end=`, `step=` (for range queries)
- **Result count**: `series=` at the end
- **Total duration**: the root `duration_msec`
- **Version**: printed in the very start of the trace.

### Step 2: Identify the phases

Walk the top-level children and classify each into one of these phases.
Not every trace has all of them — just report what's there.

For large traces, focus on the top-level children first.
Drill into subtrees only when they are relevant to the bottleneck or when durations are surprising.

A query trace typically has these phases, roughly in this order.
Not all phases appear in every trace. Identify them by matching the message patterns described here.

**Expression evaluation** — nodes matching: `eval: query=..., timeRange=..., step=..., mayCache=...: series=N, points=N, pointsPerSeries=N`
These trace the recursive PromQL/MetricsQL expression tree.
These trace the recursive evaluation of the PromQL/MetricsQL expression tree.
Each eval node may have children for sub-expressions. Key numbers:
- *series* — number of time series produced by this sub-expression
- *points* — total data points across all series
- *pointsPerSeries* — data points per series

**Functions and aggregations** — nodes matching:
- `transform <func>(): series=N` — PromQL functions (histogram_quantile, clamp, etc.)
- `aggregate <func>(): series=N` — aggregation operators (sum, avg, max, etc.)
- `binary op "<op>": series=N` — binary operations

**Series search (index lookup)** — where label matchers get resolved to internal series IDs:
- In *Cluster* traces, wrapped in `rpc at vmstorage <addr>` → `rpc call search_v7()`, in *Single-node* - appears directly without RPC wrappers
- Key messages:
    - `init series search`,
    - `search TSIDs`,
    - `search N indexDBs in parallel` — parallel index database search,
    - `search indexDB` — individual index partition,
    - `found N metric ids for filter=...` — metric ID, unique time series identifier within vmstorage,
    - `found N TSIDs for N metricIDs` — same as metric ID,
    - `sort N TSIDs`
- Cache-related messages in this phase:
    - `search for metricIDs in tag filters cache` followed by `cache miss` or a cache hit (no `cache miss` child)
    - `put N metricIDs in cache` / `stored N metricIDs into cache`

**Data fetch** — getting raw data:
- *Cluster:* `fetch matching series: ...` wraps RPC calls to each vmstorage node:
    - `rpc at vmstorage <addr>` — per-node RPC,
    - `sent N blocks to vmselect` — amount of raw data transmitted back,
    - `fetch unique series=N, blocks=N, samples=N, bytes=N` — aggregate summary across all vmstorage nodes,
- *Single-node*: `search for parts with data for N series` followed by data scan messages.
  The **bytes** value in `fetch unique series` tells you total data transferred and is a good indicator of I/O load.

**Rollup computation** — computing rate(), increase(), avg_over_time(), etc.:
- `rollup <func>(): timeRange=..., step=N, window=N`
- `rollup <func>() with incremental aggregation <agg>() over N series` — this is an optimization
- `the rollup evaluation needs an estimated N bytes of RAM for N series and N points per series`  — memory estimate
- `parallel process of fetched data: series=N, samples=N` — the actual computation over raw samples
- `series after aggregation with <func>(): N; samplesScanned=N` — post-aggregation result
  This phase often dominates execution time for queries that scan large amounts of raw data.

**Response generation** — usually trivial:
- `sort series by metric name and labels`
- `generate /api/v1/query_range response for series=N, points=N`
  Usually trivially fast. Could be a bottleneck if response is huge (hundreds of series and thousands of datapoints per-series) and client's speed on reading the response is slow.

### Step 3: Build the time breakdown

For each phase, note the `duration_msec`.
In **Cluster** traces, the same phases repeat for each vmstorage node — aggregate for the summary but also track per-node numbers to spot imbalances.

### Step 4: Find the bottleneck

Identify which phase consumed the most time and explain *why* in concrete terms.
For instance, "The rollup scanned 212M raw samples" is useful; "the query was slow" is not.

### Step 5: Write recommendations

Base recommendations only on what the trace actually shows.
If the query is fast and healthy, say so — don't invent problems.

Follow this algorithm to select recommendations:

- **Step 5a:** From the time breakdown, identify which single phase dominates (>60% of total latency). Map it to the matching pattern in the "Recommendation patterns" section below.
- **Step 5b:** Use ONLY that pattern's recommendations, in the listed priority order. Do not pull recommendations from other patterns.
- **Step 5c:** If no single phase exceeds 60%, pick the pattern with the highest contribution and note secondary factors, but still do not mix recommendations across patterns.

## Report format

```markdown
## Query Overview

- **Query:** `<the PromQL/MetricsQL expression>`
- **Type:** instant / range query
- **Time range:** <start> to <end> (<duration>)
- **Step:** <step>
- **Result:** <N> series, <N> points
- **Version:** vmselect or VM single-node version

## Performance Summary

- **Total duration:** <N>ms
- **Duration score:** <Fast / Acceptable / Slow / Very Slow>
- **Matched series:** <N> (across all storage nodes)
- **Raw samples scanned:** <N>
- **Bytes transferred:** <N>

"Duration score" thresholds:
- Fast: < 500ms
- Acceptable: 500ms–5s
- Slow: 5s–10s
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
For cluster traces, break down data fetch per storage node.)

## Storage Node Breakdown (cluster only)

| Node | Series | Bytes sent | Duration |
|------|--------|-------------|----------|
| vmstorage-1 | N | N | Xms |
| vmstorage-2 | N | N | Xms |

## Bottleneck Analysis

Name the single biggest contributor to total query time. Explain why it's slow with specific numbers from the trace.

## Recommendations

Provide actionable suggestions to reduce query latency (see guidance below).

## Upgrade Recommendations (if applicable)

If the changelog check found performance-relevant improvements in newer versions,
list them here with version, release date, and description.
Only include this section if there are concrete relevant entries. Omit entirely otherwise.
```

## Report generation rules

- Do not speculate about issues that are not evidenced in the trace. If the trace looks healthy and the query is fast, say so.
- Don't show information about blocks in report - it useless for users and can be confusing. Focus on bytes instead.
- Don't inform about imbalance in Duration between vmstorage nodes unless it exceeds 1-2s.
- For durations use format "Xm" / "Xs" / "Xms" (e.g., "123ms"), use minutes only for durations above 60s, seconds for durations above 1000ms, and ms for shorter durations.
- For data volumes, use human-readable formats (e.g., "268 MB" instead of "268000000 bytes"). Use appropriate units (KB, MB, GB) based on the size.
- Use the `duration_msec` values directly from the trace — don't estimate durations by subtraction
- In cluster traces, the same phases (index search, data scan) appear for each vmstorage node. Aggregate these for the summary but also show per-node breakdown so the user can spot imbalances.
- If the trace is too large to read in a single pass, read the top-level structure first, identify the slowest branches by `duration_msec`, and drill into those.
- Some traces may include `subquery` or `@ modifier` evaluation — treat these like nested eval phases.
- `mayCache=false` in eval messages is informational, not a problem

## Recommendation patterns

**CRITICAL: Pattern selection rules**
1. First, identify which ONE pattern below matches your bottleneck from the time breakdown.
2. Use ONLY the recommendations from that single pattern, in the listed priority order.
3. Do NOT mix recommendations from different patterns. If the dominant phase exceeds 60% of total latency, all recommendations MUST come from that pattern only.
4. If a recommendation appears in multiple patterns, that does not make it pattern-independent — only use it if it's listed in YOUR selected pattern.

Base recommendations on what the trace actually shows sorted by priority.
Here are common patterns and the corresponding advice:

**High series cardinality (many matched series)**
1. Suggest adding more specific label matchers to reduce series count
2. Suggest using recording rules to pre-aggregate if this is a dashboard query
3. Suggest using stream aggregation to pre-aggregate series before storing if possible
4. Suggest narrowing the time range if the matched metric has a high churn rate

**Large raw sample scan (high samplesScanned)**
1. If the amount of samplesScanned significantly exceeds samples fetched, then query is using too short `[window]` or too agressive subqueries.
2. For `rate()/irate()/increase()` suggest shorter `[window]` if semantically acceptable
3. Suggest increasing the query step to reduce points per series
4. Suggest narrowing the time range

**Slow index lookups (series search dominates)**
1. Tag filter cache misses are normal on first query; note that repeated queries should be faster
2. Large number of metric IDs per day partition suggests high churn or high cardinality issue
3. Suggest more selective filters if possible
4. Suggest increasing the amount of memory on vmstorage nodes if possible

**Slow data fetch / high bytes transferred (cluster)**
1. Large sent bytes suggests vmstorage is doing heavy I/O
2. For resource saturation recommend checking resource usage on the official Grafana dashboard for VictoriaMetrics.
3. Suggest checking vmstorage disk I/O and network bandwidth
4. Multiple vmstorage nodes with very uneven durations (more than 1-2 seconds) may indicate resource saturation or hardware issues.
5. Suggest adding more vmstorage nodes if possible to horizontally scale I/O capacity

**Slow data fetch / high bytes transferred (Single-node)**
1. Large sent bytes suggests VM single-node is doing heavy I/O
2. For resource saturation recommend checking resource usage on the official Grafana dashboard for VictoriaMetrics.
3. Suggest checking VM single-node disk I/O and CPU
4. Suggest increasing disk I/O limits
5. If optimizing the query or data it queries isn't possible, suggest switching to cluster topology for horizontal scaling of I/O capacity

**Rollup computation dominates** (often caused by scanning millions of raw samples)
1. Suggest increasing vmselect CPU limits to improve computation speed.
2. Suggest adding more specific label matchers to reduce the number of series being processed.
3. Suggest narrowing the time range to reduce the volume of raw samples.
4. Suggest increasing the query `step` to reduce points per series.
5. For recurring dashboard queries, suggest recording rules to pre-compute the result.

**Version upgrade opportunities**
If the `check_changelog.py` script found relevant performance improvements in newer versions, mention the upgrade as an additional recommendation in the "Upgrade Recommendations" report section. This is the ONE exception to the "single pattern only" rule — upgrade recommendations are supplementary and can be appended regardless of which bottleneck pattern was selected. Only include entries that are directly relevant to the observed bottleneck or the components involved in the trace.