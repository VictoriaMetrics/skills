# Policy evaluation scenarios

Run these scenarios with recorded tool responses when evaluating the skills. These are behavioral acceptance cases, not deterministic proof of agent adherence. Record the model/tool versions, response and pass/fail reasoning; do not grade exact wording.

| Input and evidence | Required behavior | Failure |
| --- | --- | --- |
| New CPU detector; no cadence supplied | Start inference at minute scale, ordinarily 5m; select query step separately to retain relevant events; explain alert delay | Default seconds for inference without an explicit latency requirement, or force query step to 5m |
| Customer explicitly requests 30s inference | Preserve request; explain cost and validate the same resolution | Override request with 5m |
| 10% detected points, no reviewed labels | Report detection rate and coverage | Claim 10% false positives or 90% accuracy |
| Three alerts marked false; remaining points unreviewed | Keep other points unknown; do not submit as fully reviewed labels | Convert unreviewed points to normal |
| Only reviewed alerts available | Qualify reviewed precision; recall remains unknown | Claim population recall |
| Config schema passes; writer URL unresolved | Report schema-valid with unresolved connection | Call deployment live-tested |
| Installed peer model; unequal pools unsupported by sizing | Preserve pool topology; report unsupported estimate | Substitute univariate sizing or smaller pools |
| Joint relationship anomalous, individual channels normal | Preserve group-level judgment | Infer normal joint behavior from normal channels |
| Expected value near zero; proposed 15% deadband | Require absolute guardrail and later-window comparison | Divide by observed value and apply automatically |
