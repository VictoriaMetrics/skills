# Dynamic preset evaluation scenarios

These are planned agent acceptance cases, not results of an executed model evaluation. Record the model, tool versions, evidence and pass/fail reasoning. Deterministic helper checks run with `python3 -m unittest discover -s plugins/vmanomaly/tests -p 'test_*.py'`.

| Situation | Required outcome |
| --- | --- |
| Discovery returns fewer than the requested items and `completeness: unknown` | Preserve uncertainty; do not use the count as exact fleet cardinality |
| Ten metadata calls have been made with no viable signal | Stop discovery, explain evidence and request narrower scope rather than loop |
| Installed 1.31.0 has sizing but no discovery/artifact endpoint | Keep sizing available; use an authorized bounded alternative or report the specific missing capability |
| Input and prediction storage use different tenants | Generate distinct reader/writer destinations and make vmalert query prediction storage |
| Only a deterministic capacity threshold is actionable | Produce a static rule with provenance; do not force an ML bundle |
| Peer pools differ in size or lose members | Preserve whole populations; do not replace unsupported sizing with smaller/univariate workloads |
| A dashboard uses unsupported metric suffixes or lacks expected variables | Stop automatic dashboard adaptation and identify the manual work |
| Schema, Compose and Helm checks pass without a running deployment | Report those passes; keep startup, delivery, incident navigation and dashboard checks pending |
