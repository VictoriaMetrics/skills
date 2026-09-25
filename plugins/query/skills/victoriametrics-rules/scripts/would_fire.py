#!/usr/bin/env python3
"""Report when an alerting rule would have fired over a past window.

Runs the rule's own expression as a range query and applies the `for` duration to
the result. Reads only. Nothing is written to the datasource, which is what makes
this safe against a production deployment, unlike `vmalert -replay`.

The expression must include its comparison, e.g. `... > 0.05`. A filtering
comparison drops the samples where it is false, so every point which comes back
is a moment the condition held.

Credentials come from the curl config file in $VM_CURL_CONFIG, as in every other
call of this skill. Exit code 0 means at least one series fires, 1 means none does,
and 2 means the check could not run: read the message, it is not a verdict.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h|d|w|y)")
DURATION_UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}
# An agent's shell call is killed at 120 s.
MAX_TIME_SECONDS = 90


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(2)


def curl_command(url, query, start, end, step):
    # The token stays in $VM_CURL_CONFIG, never in the process arguments.
    return ["curl", "-q", "--config", os.environ.get("VM_CURL_CONFIG") or "/dev/null",
            "-sS", "--fail-with-body", "--max-time", str(MAX_TIME_SECONDS),
            "--data-urlencode", "query=" + query,
            "--data-urlencode", "start=" + start,
            "--data-urlencode", "end=" + end,
            "--data-urlencode", "step=" + step,
            # Named, so a URL starting with "-" is not read as an option.
            "--url", url.rstrip("/") + "/api/v1/query_range"]


def fetch_json(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        fail("curl not found: the script reaches the datasource through curl")
    if out.returncode != 0:
        fail("datasource request failed: %s %s" % (out.stderr.strip(), out.stdout.strip()[:400]))
    try:
        return json.loads(out.stdout)
    except ValueError:
        fail("datasource did not return JSON: %s" % out.stdout.strip()[:400])


def series_of(payload):
    if payload.get("status") != "success":
        fail("datasource error: %s" % payload.get("error", payload))
    # A query limit can cut the result short and still answer "success".
    for warning in payload.get("warnings") or []:
        print("WARNING from the datasource: %s" % warning)
        print("  The result below may be incomplete. Do not treat it as final.")
    return payload["data"]["result"]


def fire_time(timestamps, step_seconds, for_seconds):
    """First moment the condition has held continuously for `for_seconds`.

    The pending clock restarts on a gap, because a missing point means the
    condition was false then, which is how vmalert treats it. Elapsed time is
    measured from the start of the run: counting points instead reports the fire
    time one step early, since N points span only (N-1) steps.
    """
    if not timestamps:
        return None, None
    run_start = timestamps[0]
    if for_seconds == 0:
        return timestamps[0], run_start
    for prev, cur in zip(timestamps, timestamps[1:]):
        if (cur - prev).total_seconds() > step_seconds:
            run_start = cur
        elif (cur - run_start).total_seconds() >= for_seconds:
            return cur, run_start
    return None, run_start


def parse_duration(text):
    text = text.strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = DURATION_PART.findall(text)
    if parts and "".join(n + u for n, u in parts) == text:
        return sum(float(n) * DURATION_UNITS[u] for n, u in parts)
    fail("cannot parse duration %r; use 30s, 1h30m, 500ms or a number of seconds" % text)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", required=True, help="datasource base URL, as vmalert's -datasource.url")
    p.add_argument("--query", required=True, help="the rule expr, comparison included")
    p.add_argument("--start", required=True, help="RFC3339 or unix seconds")
    p.add_argument("--end", required=True, help="RFC3339 or unix seconds")
    p.add_argument("--step", default="1m", help="evaluation step, default the group interval you use")
    p.add_argument("--for", dest="for_", default="0s", help="the rule's for: duration")
    return p.parse_args()


def report_series(s, step_s, for_s):
    """Print one series' verdict and return whether it fires."""
    ts = [datetime.fromtimestamp(v[0], timezone.utc) for v in s["values"]]
    labels = ",".join("%s=%s" % kv for kv in sorted(s["metric"].items())) or "{}"
    fired, run_start = fire_time(ts, step_s, for_s)
    print("%s" % labels)
    print("  condition true at %d of %d steps, first %s, last %s"
          % (len(ts), int((ts[-1] - ts[0]).total_seconds() // step_s) + 1,
             ts[0].isoformat(), ts[-1].isoformat()))
    if fired:
        print("  fires %s (pending from %s, for=%gs)"
              % (fired.isoformat(), run_start.isoformat(), for_s))
    else:
        print("  never fires: no unbroken run reaches for=%gs" % for_s)
    return fired is not None


def main():
    args = parse_args()
    step_s = parse_duration(args.step)
    if step_s <= 0:
        fail("--step must be greater than zero")
    for_s = parse_duration(args.for_)
    series = series_of(fetch_json(curl_command(args.url, args.query, args.start, args.end, args.step)))
    if not series:
        print("condition never true in this window, so the rule would not fire")
        print("if that is a surprise, the selector may match nothing: check it with /api/v1/series")
        return 1
    # The rule fires when any of its series does. Every series is still reported.
    fires = [report_series(s, step_s, for_s) for s in series]
    return 0 if any(fires) else 1


if __name__ == "__main__":
    sys.exit(main())
