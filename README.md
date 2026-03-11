# VictoriaMetrics skills

A collection of agent skills for interacting with the VictoriaMetrics ecosystem.
These skills help AI agents and automation tools understand, operate, and troubleshoot VictoriaMetrics products such as metrics, logs, and traces storage.

## Available Skills

| Skill | Purpose |
|-------|---------|
| [victoriametrics-query](skills/victoriametrics-query/SKILL.md) | Run PromQL/MetricsQL queries, discover metrics and labels, inspect alerts, rules, TSDB status, and debug configs |
| [victorialogs-query](skills/victorialogs-query/SKILL.md) | Search logs with LogsQL, run stats queries, discover fields and streams, analyze log volume |
| [victoriatraces-query](skills/victoriatraces-query/SKILL.md) | Discover services and operations, search traces by duration/tags, retrieve traces by ID, map dependencies |
| [alertmanager-query](skills/alertmanager-query/SKILL.md) | List active/silenced alerts, create and manage silences, check alert inhibition state |
| [vm-trace-analyzer](skills/vm-trace-analyzer/SKILL.md) | Analyze VictoriaMetrics query trace JSON to diagnose slow queries and produce performance reports |
| [investigating-with-observability](skills/investigating-with-observability/SKILL.md) | Orchestrate multi-signal investigations across metrics, logs, and traces with structured phases |

## Usage

These skills are designed for use with [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and compatible AI agents. Each skill is invoked automatically when the agent detects a matching request, or manually via slash commands:

```
/victoriametrics-query    — query metrics, discover labels, check alerts and rules
/victorialogs-query       — search logs, run stats, discover fields
/victoriatraces-query     — search traces, discover services, map dependencies
/alertmanager-query       — list alerts, manage silences
/investigating-with-observability — structured multi-signal investigation
```

**Example prompts that trigger skills:**

- "What alerts are currently firing?" → `alertmanager-query`
- "Show me error logs for namespace production in the last hour" → `victorialogs-query`
- "Find slow traces for the checkout service" → `victoriatraces-query`
- "What's the request rate for my-api over the last 6 hours?" → `victoriametrics-query`
- "This query is slow, here's the trace JSON — analyze it" → `vm-trace-analyzer`
- "Pod X is crash looping — investigate" → `investigating-with-observability`

## Environment Variables

All skills use `curl` and expect these environment variables:

```bash
VM_METRICS_URL        # VictoriaMetrics query endpoint (e.g., http://localhost:8428)
VM_LOGS_URL           # VictoriaLogs endpoint (e.g., http://localhost:9428)
VM_TRACES_URL         # VictoriaTraces with /select/jaeger prefix (e.g., http://localhost:10428/select/jaeger)
VM_ALERTMANAGER_URL   # AlertManager endpoint (optional)
VM_AUTH_HEADER        # Auth header value (empty for local, set for prod)
```
