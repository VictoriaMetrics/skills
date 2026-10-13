# Recording rules

A recording rule precomputes an expression and writes the result back under a new metric name, so
it has no threshold, no `for`, and no alert. Its shape in `/api/v1/rules` differs from an alerting
rule in ways that look like faults if you expect the alerting fields:

| Field | Recording rule |
|---|---|
| `state` | **empty string**, not `inactive`. There is nothing to fire |
| `type` | `recording` |
| `lastSamples` | the number of output series it produced. This is the health signal |

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/api/v1/rules" \
  | jq -r '.data.groups[].rules[] | select(.type=="recording")
           | "\(.name)\thealth=\(.health)\tsamples=\(.lastSamples)\terr=\(.lastError)"'
```

Verify it by querying the output metric on the datasource, not by looking for an alert:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s \
  --data-urlencode 'query=job:http_requests:rate5m' \
  "$VM_METRICS_URL/api/v1/query" | jq '.data.result'
```

An empty result with `lastSamples` above zero means vmalert computed the series but they are not
reaching storage, which is a remote write problem. Read vmalert's remote write counters to
confirm it:

```bash
curl -q --config "${VM_CURL_CONFIG:-/dev/null}" -s "$VMALERT_URL/metrics" \
  | jq -Rr 'select(test("^vmalert_remotewrite_(sent_rows|errors|dropped_rows)_total[{ ]"))'
```

`errors_total` or `dropped_rows_total` rising means the writes fail. `sent_rows_total` rising with
no data in `$VM_METRICS_URL` means vmalert writes to a different place than you query: ask where
`-remoteWrite.url` points. Name recording rules
`level:metric:operation`, as in `job:http_requests:rate5m`, so the output name says what it
aggregates.

Three things that differ from alerting rules:

- vmalert refuses to start when the config holds any recording rule and `-remoteWrite.url` is
  unset, with `config contains recording rules but -remoteWrite.url isn't set`. There is nowhere
  to put the output otherwise.
- `would_fire.py` does not apply. It needs a comparison in the expression to find the points
  where a condition held, and a recording rule has none.
- It writes no `ALERTS`, so Workflow A in SKILL.md does not apply. Query the output metric over the
  window instead.
