#!/usr/bin/env python3
"""Report when an alerting rule would have fired over a past window.

Repeats what vmalert sends: one instant query per evaluation, at each multiple of
the group interval, with vmalert's `step`. Then it applies `for` per series the
way vmalert does. Reads only. Nothing is written to the datasource, which is what
makes this safe against a production deployment, unlike `vmalert -replay`.

The expression must include its comparison, e.g. `... > 0.05`. A filtering
comparison drops the series where it is false, so every series which comes back
is one whose condition held at that evaluation.

Credentials come from the curl config file in $VM_CURL_CONFIG, as in every other
call of this skill. Exit code 0 means at least one series fires inside the window,
1 means none does, and 2 means the check could not run or its result is
incomplete: read the message, it is not a verdict.
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h|d|w|y)")
DURATION_UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}
# An agent's shell call is killed at 120 s.
MAX_TIME_SECONDS = 90
MAX_EVALUATIONS = 1000
PARALLEL_QUERIES = 8


class CheckError(Exception):
    """The check could not run, or its result is incomplete."""


def curl_command(url, query, at, eval_step, timeout):
    # The token stays in $VM_CURL_CONFIG, never in the process arguments.
    return ["curl", "-q", "--config", os.environ.get("VM_CURL_CONFIG") or "/dev/null",
            "-sS", "--fail-with-body", "--max-time", str(max(1, int(timeout))),
            "--data-urlencode", "query=" + query,
            "--data-urlencode", "time=%.3f" % at,
            "--data-urlencode", "step=%gs" % eval_step,
            # Named, so a URL starting with "-" is not read as an option.
            "--url", url.rstrip("/") + "/api/v1/query"]


def fetch_json(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise CheckError("curl not found: the script reaches the datasource through curl")
    if out.returncode != 0:
        raise CheckError("datasource request failed: %s %s"
                         % (out.stderr.strip(), out.stdout.strip()[:400]))
    try:
        return json.loads(out.stdout)
    except ValueError:
        raise CheckError("datasource did not return JSON: %s" % out.stdout.strip()[:400])


def series_of(payload):
    if payload.get("status") != "success":
        raise CheckError("datasource error: %s" % payload.get("error", payload))
    # A query limit can cut the result short and still answer "success".
    warnings = payload.get("warnings") or []
    if warnings:
        raise CheckError("the datasource warned that the result may be incomplete, so there is no "
                         "verdict: %s" % "; ".join(warnings))
    return payload["data"]["result"]


def parse_duration(text):
    text = text.strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = DURATION_PART.findall(text)
    if parts and "".join(n + u for n, u in parts) == text:
        return sum(float(n) * DURATION_UNITS[u] for n, u in parts)
    raise CheckError("cannot parse duration %r; use 30s, 1h30m, 500ms or a number of seconds"
                     % text)


def parse_time(text):
    text = text.strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise CheckError("cannot parse time %r; use RFC3339 such as 2026-09-22T01:00:00Z or "
                         "unix seconds" % text)


def evaluation_times(start, end, interval, for_s):
    # vmalert aligns evaluations to multiples of the interval (eval_alignment). Starting
    # twice `for` early finds when an alert already pending or firing at `start` began.
    first = math.ceil((start - 2 * for_s - interval) / interval) * interval
    last = math.floor(end / interval) * interval
    count = int(round((last - first) / interval)) + 1
    return [first + i * interval for i in range(max(count, 0))]


def run_evaluations(url, query, times, eval_step):
    deadline = time.monotonic() + MAX_TIME_SECONDS

    def one(at):
        left = deadline - time.monotonic()
        if left <= 0:
            raise CheckError("the check ran out of time after %d s; narrow the window"
                             % MAX_TIME_SECONDS)
        return at, series_of(fetch_json(curl_command(url, query, at, eval_step, left)))

    with ThreadPoolExecutor(PARALLEL_QUERIES) as pool:
        futures = [pool.submit(one, at) for at in times]
        try:
            return [f.result() for f in futures]
        except CheckError:
            for f in futures:
                f.cancel()
            raise


def episodes(true_times, times, for_s, keep_s):
    """Split one series' true evaluations into vmalert episodes.

    The alert goes pending at the first true evaluation (activeAt) and fires at the
    first one at least `for` after it. A missing series deletes a pending alert,
    which is how an empty result resets `for`. A firing alert resolves at the first
    evaluation at least `keep_firing_for` after the series went missing, and a true
    evaluation before that keeps it firing. This follows vmalert's alerting.go.
    """
    result, current = [], None
    for at in times:
        if at in true_times:
            if current is None:
                current = {"active": at, "fired": None, "resolved": None, "kept": None}
            current["kept"] = None
            if current["fired"] is None and at - current["active"] >= for_s:
                current["fired"] = at
        elif current is not None:
            if current["fired"] is not None and current["kept"] is None:
                current["kept"] = at
            if current["fired"] is None or at - current["kept"] >= keep_s:
                current["resolved"] = at
                result.append(current)
                current = None
    if current is not None:
        result.append(current)
    return result


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def describe(e, times, start, end, for_s):
    """Return one episode as text, and whether it fires inside the window."""
    end_text = ("resolved %s" % iso(e["resolved"]) if e["resolved"] is not None
                else "still active at %s" % iso(times[-1]))
    if e["active"] == times[0]:
        # The run began before the first evaluation, so its activeAt and fire time are unknown.
        return ("already true at %s, the first evaluation checked; %s; start earlier to see "
                "when it went pending" % (iso(times[0]), end_text)), e["fired"] is not None
    begin = iso(e["active"])
    if e["fired"] is not None and e["fired"] >= start:
        return "pending %s, fires %s, %s" % (begin, iso(e["fired"]), end_text), e["fired"] <= end
    if e["fired"] is not None:
        return ("pending %s, firing since %s, before the window, %s"
                % (begin, iso(e["fired"]), end_text)), False
    if e["resolved"] is None:
        return "pending %s, never fires, %s" % (begin, end_text), False
    return ("pending %s, never fires, cleared %s before for=%gs"
            % (begin, iso(e["resolved"]), for_s)), False


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", required=True, help="datasource base URL, as vmalert's -datasource.url")
    p.add_argument("--query", required=True, help="the rule expr, comparison included")
    p.add_argument("--start", required=True, help="RFC3339 or unix seconds")
    p.add_argument("--end", required=True, help="RFC3339 or unix seconds")
    p.add_argument("--step", default="1m", help="the group interval, one evaluation per step")
    p.add_argument("--for", dest="for_", default="0s", help="the rule's for: duration")
    p.add_argument("--keep-firing-for", default="0s", help="the rule's keep_firing_for duration")
    p.add_argument("--eval-step", default="5m",
                   help="the step vmalert sends, from the curl field of /api/v1/rule; default "
                        "-datasource.queryStep, 5m; 0 means the interval")
    return p.parse_args()


def check(args):
    interval = parse_duration(args.step)
    if interval <= 0:
        raise CheckError("--step must be greater than zero")
    for_s = parse_duration(args.for_)
    keep_s = parse_duration(args.keep_firing_for)
    # -datasource.queryStep=0 makes vmalert send the rule's interval as step.
    eval_step = parse_duration(args.eval_step) or interval
    start, end = parse_time(args.start), parse_time(args.end)
    if end < start:
        raise CheckError("--end is before --start")
    times = evaluation_times(start, end, interval, for_s)
    if len(times) > MAX_EVALUATIONS:
        raise CheckError("%d evaluations is more than %d; narrow the window or raise --step"
                         % (len(times), MAX_EVALUATIONS))
    if not times:
        raise CheckError("no evaluation falls inside the window; widen it")

    true_at = true_times_by_series(run_evaluations(args.url, args.query, times, eval_step))
    return report(true_at, times, start, end, for_s, keep_s)


def true_times_by_series(results):
    true_at = {}
    for at, series in results:
        for s in series:
            # vmalert drops __name__ from alert labels, so the report does too.
            key = tuple(sorted((k, v) for k, v in s["metric"].items() if k != "__name__"))
            true_at.setdefault(key, set()).add(at)
    return true_at


def report(true_at, times, start, end, for_s, keep_s):
    """Print each series' episodes in the window and return the exit code."""
    fires, reported = False, False
    for key in sorted(true_at):
        eps = [e for e in episodes(true_at[key], times, for_s, keep_s)
               if e["resolved"] is None or e["resolved"] > start]
        if not eps:
            continue
        reported = True
        print("{%s}" % ",".join("%s=%s" % (k, json.dumps(v)) for k, v in key))
        for e in eps:
            text, fired = describe(e, times, start, end, for_s)
            print("  " + text)
            fires = fires or fired
    if not reported:
        print("condition never true in this window, so the rule would not fire")
        print("if that is a surprise, the selector may match nothing: check it with /api/v1/series")
    return 0 if fires else 1


def main():
    try:
        return check(parse_args())
    except CheckError as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
