---
name: alertmanager-hol-guard
description: >
  Protect state-changing AlertManager workflows from a supported local coding-agent harness with HOL Guard.
  Use before creating or deleting silences when the user wants a local pre-tool approval and evidence boundary.
  Pair with alertmanager-query for the actual AlertManager API semantics and curl commands.
allowed-tools: Bash(pipx:*), Bash(hol-guard:*)
---

# AlertManager + HOL Guard

Use HOL Guard as an additional local agent-runtime boundary before mutation-bearing AlertManager work. Keep `alertmanager-query` authoritative for AlertManager endpoints, payloads, authentication, timestamps, and response handling.

HOL Guard protects the supported local coding-agent harness before tools run. It does not run inside VictoriaMetrics or AlertManager, replace server-side authorization, or validate arbitrary AlertManager API payloads.

## Set up the protected harness

If HOL Guard is missing and runtime protection was requested, prefer an isolated install:

```bash
pipx install hol-guard
```

Initialize Guard and detect the active local harness:

```bash
hol-guard bootstrap
hol-guard detect --json
```

Use the exact supported harness identifier returned by `detect`:

```bash
hol-guard install <harness>
hol-guard run <harness> --dry-run
hol-guard run <harness>
hol-guard status
```

For Hermes, use its dedicated bootstrap flow:

```bash
hol-guard hermes bootstrap
```

Do not claim the session is protected unless current Guard status or doctor output proves it. Run the AlertManager workflow from the protected harness launched by `hol-guard run`.

## Route AlertManager work to the maintained skill

Once the protected harness is active, use `alertmanager-query` for the actual API workflow. That skill remains the source of truth for:

- listing alerts and silences,
- creating silences,
- retrieving silence state,
- expiring/deleting silences,
- authentication through `VM_CURL_CONFIG`, and
- AlertManager-specific endpoint and payload details.

If `alertmanager-query` is unavailable, stop and install or load the maintained query plugin instead of reconstructing AlertManager mutation commands from memory.

## Require Guard before state changes

Use the protected harness before agent-driven AlertManager mutations, especially creating a silence or expiring/deleting one. Preserve the confirmation and safety behavior documented by `alertmanager-query`.

If Guard denies, requests review, errors, times out, or cannot prove the protected harness is active, stop before the AlertManager mutation. Do not retry the same write from an unprotected session.

Review local Guard state with:

```bash
hol-guard approvals
hol-guard approvals open
hol-guard receipts
```

Read-only alert and silence queries remain governed by `alertmanager-query`; do not create a mutation merely to prove Guard is working.

## Evidence and troubleshooting

```bash
hol-guard doctor
hol-guard doctor <harness> --json
hol-guard receipts
hol-guard inventory
hol-guard events
```

Report separately:

1. what AlertManager mutation the maintained skill prepared,
2. what Guard proved, denied, or routed to review at the local harness boundary,
3. the AlertManager response after an approved protected mutation, and
4. any remaining operator action.

Canonical HOL Guard setup: https://github.com/hashgraph-online/hol-guard-plugin/tree/main/skills/hol-guard
