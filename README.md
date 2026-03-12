# VictoriaMetrics skills

A collection of agent skills for interacting with the VictoriaMetrics ecosystem.
These skills help AI agents and automation tools understand, operate, and troubleshoot VictoriaMetrics products such as metrics, logs, and traces storage.

## Available Plugins

| Plugin | Skills | Purpose |
|--------|--------|---------|
| [query](plugins/query/) | victoriametrics-query, victorialogs-query, victoriatraces-query, alertmanager-query | Query metrics, logs, traces, and alerts |
| [diagnostics](plugins/diagnostics/) | vm-trace-analyzer, investigating-with-observability, victoriametrics-cardinality-analysis, victoriametrics-unused-metrics-analysis | Query trace analysis, multi-signal investigations, cardinality optimization, unused metric detection |

## Installation

### Via [skills.sh](https://skills.sh)

Install all skills:

```
npx skills add VictoriaMetrics/skills
```

Install a specific skill:

```
npx skills add VictoriaMetrics/skills --skill victoriametrics-query
npx skills add VictoriaMetrics/skills --skill victorialogs-query
npx skills add VictoriaMetrics/skills --skill victoriatraces-query
npx skills add VictoriaMetrics/skills --skill alertmanager-query
npx skills add VictoriaMetrics/skills --skill investigating-with-observability
npx skills add VictoriaMetrics/skills --skill vm-trace-analyzer
npx skills add VictoriaMetrics/skills --skill victoriametrics-cardinality-analysis
npx skills add VictoriaMetrics/skills --skill victoriametrics-unused-metrics-analysis
```

### Via Claude Code plugin marketplace

Add the marketplace source:

```
/plugin marketplace add VictoriaMetrics/skills
```

Install plugins:

```
/plugin install query@victoriametrics-tools # Query VictoriaStack components and AlertManager
/plugin install diagnostics@victoriametrics-tools # Troubleshooting and query trace analysis
```

## Skills

### Query plugin

| Skill | Purpose |
|-------|---------|
| victoriametrics-query | Run PromQL/MetricsQL queries, discover metrics and labels, inspect alerts, rules, TSDB status, and debug configs |
| victorialogs-query | Search logs with LogsQL, run stats queries, discover fields and streams, analyze log volume |
| victoriatraces-query | Discover services and operations, search traces by duration/tags, retrieve traces by ID, map dependencies |
| alertmanager-query | List active/silenced alerts, create and manage silences, check alert inhibition state |

### Diagnostics plugin

| Skill | Purpose |
|-------|---------|
| vm-trace-analyzer | Analyze VictoriaMetrics query trace JSON to diagnose slow queries and produce performance reports |
| investigating-with-observability | Orchestrate multi-signal investigations across metrics, logs, and traces with structured phases |
| victoriametrics-cardinality-analysis | Analyze time series cardinality to find optimization opportunities — unused metrics, high-cardinality labels, histogram bloat |
| victoriametrics-unused-metrics-analysis | Find unused and rarely-queried metrics, then suggest drop rules and relabel configs to reduce waste |

## Usage

Once installed, skills are available as slash commands and are also triggered automatically when Claude detects a matching request:

```
/query:victoriametrics-query            - query metrics, discover labels, check alerts and rules
/query:victorialogs-query               - search logs, run stats, discover fields
/query:victoriatraces-query             - search traces, discover services, map dependencies
/query:alertmanager-query               - list alerts, manage silences
/diagnostics:vm-trace-analyzer          - perform an analysis of the query performance based on provided trace
/diagnostics:investigating-with-observability - structured multi-signal investigation
/diagnostics:victoriametrics-cardinality-analysis  - cardinality analysis and optimization recommendations
/diagnostics:victoriametrics-unused-metrics-analysis - find unused metrics and suggest drop rules
```

**Example prompts that trigger skills:**

- "What alerts are currently firing?" → `alertmanager-query`
- "Show me error logs for namespace production in the last hour" → `victorialogs-query`
- "Find slow traces for the checkout service" → `victoriatraces-query`
- "What's the request rate for my-api over the last 6 hours?" → `victoriametrics-query`
- "This query is slow, here's the trace JSON — analyze it" → `vm-trace-analyzer`
- "Pod X is crash looping — investigate" → `investigating-with-observability`
- "Which metrics have the highest cardinality?" → `victoriametrics-cardinality-analysis`
- "Find metrics that nobody queries" → `victoriametrics-unused-metrics-analysis`

## Environment Variables

All skills use `curl` and expect these environment variables:

```bash
VM_METRICS_URL        # VictoriaMetrics query endpoint (e.g., http://localhost:8428)
VM_LOGS_URL           # VictoriaLogs endpoint (e.g., http://localhost:9428)
VM_TRACES_URL         # VictoriaTraces with /select/jaeger prefix (e.g., http://localhost:10428/select/jaeger)
VM_ALERTMANAGER_URL   # AlertManager endpoint (optional)
VM_AUTH_HEADER        # Auth header value (empty for local, set for prod)
```
