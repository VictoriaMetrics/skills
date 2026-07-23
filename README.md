# VictoriaMetrics skills

A collection of agent skills for interacting with the VictoriaMetrics ecosystem.
These skills help AI agents and automation tools understand, operate, and troubleshoot VictoriaMetrics products such as metrics, logs, and traces storage.

## Available Plugins

| Plugin | Skills | Purpose |
|--------|--------|---------|
| [query](plugins/query/) | victoriametrics-query, victorialogs-query, victoriatraces-query, alertmanager-query | Query metrics, logs, traces, and alerts |
| [diagnostics](plugins/diagnostics/) | vm-trace-analyzer, investigating-with-observability, victoriametrics-cardinality-analysis, victoriametrics-unused-metrics-analysis, stream-aggregation-helper | Query trace analysis, multi-signal investigations, cardinality optimization, unused metric detection, stream aggregation design |
| [vmanomaly](plugins/vmanomaly/) | vmanomaly-query, vmanomaly-config, vmanomaly-review | Operate the vmanomaly API, build and tune anomaly-detection configurations, and review detection quality |

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
npx skills add VictoriaMetrics/skills --skill stream-aggregation-helper
npx skills add VictoriaMetrics/skills --skill vmanomaly-query
npx skills add VictoriaMetrics/skills --skill vmanomaly-config
npx skills add VictoriaMetrics/skills --skill vmanomaly-review
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
/plugin install vmanomaly@victoriametrics-tools # Configure, operate, tune, and review anomaly detection
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
| stream-aggregation-helper | Design vmagent stream aggregation rules — gate, intake, pick interval/output/by-without, generate YAML, plan rollout, verify with `vm_streamaggr_*` |

### vmanomaly plugin

| Skill | Purpose |
|-------|---------|
| vmanomaly-query | Operate vmanomaly v1.30+ HTTP APIs for health, compatibility, schemas, profiling, shared autotune, validation, and bounded detection tasks |
| vmanomaly-config | Triage static alerting versus ML, select and tune a model from real time-series characteristics, and produce validated deployment artifacts |
| vmanomaly-review | Audit an existing configuration against runtime schemas and real data, reproduce detections, and verify proposed fixes |

Each vmanomaly skill is independently installable. When query or diagnostics skills are also
available, the vmanomaly workflows can use them for metric/log discovery, cardinality checks,
existing-alert review, and multi-signal incident correlation.

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
/diagnostics:stream-aggregation-helper             - design and verify stream aggregation rules
/vmanomaly:vmanomaly-query                         - inspect and operate the vmanomaly API
/vmanomaly:vmanomaly-config                        - build and tune a validated anomaly configuration
/vmanomaly:vmanomaly-review                        - audit an existing anomaly configuration
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
- "Help me aggregate this high-cardinality metric at vmagent" → `stream-aggregation-helper`
- "Profile this query and choose a vmanomaly model" → `vmanomaly-config`
- "Check whether my persisted vmanomaly state is compatible with v1.30" → `vmanomaly-query`
- "Review why this anomaly model produces too many detections" → `vmanomaly-review`

## Environment Variables

All skills use `curl` and expect these environment variables:

```bash
VM_METRICS_URL        # VictoriaMetrics query endpoint (e.g., http://localhost:8428)
VM_LOGS_URL           # VictoriaLogs endpoint (e.g., http://localhost:9428)
VM_TRACES_URL         # VictoriaTraces with /select/jaeger prefix (e.g., http://localhost:10428/select/jaeger)
VM_ALERTMANAGER_URL   # AlertManager endpoint (optional)
VM_ANOMALY_URL        # vmanomaly endpoint, including path prefix if configured (e.g., http://localhost:8490)
VM_CURL_CONFIG        # Path to a mode-0600 curl config file containing the auth header
                      # (leave unset for unauthenticated local instances - defaults to /dev/null)
```

### Authentication setup

Skills pass credentials to `curl` through a [curl config file](https://curl.se/docs/manpage.html#-K)
instead of command-line arguments. This keeps tokens out of process listings, shell history, and
agent transcripts. Every command uses the same pattern:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VM_METRICS_URL/api/v1/query?query=up"
```

For unauthenticated local instances no setup is needed: when `VM_CURL_CONFIG` is unset, curl reads
`/dev/null` and sends no auth header.

For authenticated instances, create a config file readable only by you and point `VM_CURL_CONFIG` at it:

```bash
mkdir -p "$HOME/.config/victoriametrics"
touch "$HOME/.config/victoriametrics/curl.conf"
chmod 0600 "$HOME/.config/victoriametrics/curl.conf"
cat > "$HOME/.config/victoriametrics/curl.conf" <<'EOF'
header = "Authorization: Bearer <token>"
EOF
export VM_CURL_CONFIG="$HOME/.config/victoriametrics/curl.conf"
```

For Basic auth, use `user = "username:password"` instead of the `header` line.

### Migrating from VM_AUTH_HEADER

Earlier versions of these skills read the auth header from the `VM_AUTH_HEADER` environment variable
(`export VM_AUTH_HEADER="Authorization: Bearer <token>"`) and passed it to curl via `-H`. That exposed
the token in process listings, shell history, and agent transcripts, so skills now read it from a curl
config file instead. `VM_AUTH_HEADER` is no longer used by any skill.

To migrate:

1. Move the header line into a mode-0600 curl config file:

   ```bash
   mkdir -p "$HOME/.config/victoriametrics"
   touch "$HOME/.config/victoriametrics/curl.conf"
   chmod 0600 "$HOME/.config/victoriametrics/curl.conf"
   printf 'header = "%s"\n' "$VM_AUTH_HEADER" > "$HOME/.config/victoriametrics/curl.conf"
   ```

2. Replace `VM_AUTH_HEADER` with `VM_CURL_CONFIG` wherever you export it (shell profile, CI secrets,
   agent configuration):

   ```bash
   export VM_CURL_CONFIG="$HOME/.config/victoriametrics/curl.conf"
   unset VM_AUTH_HEADER
   ```

3. If you never set `VM_AUTH_HEADER` (unauthenticated local instances), no action is needed.
