#!/usr/bin/env python3
"""
VictoriaMetrics trace analyzer — extracts structured data from trace JSON files.

Usage:
    python3 parse_trace.py <trace.json>                    # full summary (default)
    python3 parse_trace.py <trace.json> tree [--depth N]   # tree view to depth N
    python3 parse_trace.py <trace.json> nodes --pattern P  # find nodes by substring
"""

import json
import re
import sys


def load_trace(path):
    with open(path) as f:
        return json.load(f)


def fmt_duration(ms):
    if ms >= 60000:
        return f"{ms / 60000:.1f}m"
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms:.1f}ms"


def extract_semver(version_prefix):
    """Extract semver tuple from version prefix, e.g. 'vmselect-...-v1.130.0-...' -> (1, 130, 0)."""
    m = re.search(r'v(\d+)\.(\d+)\.(\d+)', version_prefix)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def fmt_bytes(b):
    if b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.1f} GB"
    if b >= 1024 ** 2:
        return f"{b / 1024 ** 2:.0f} MB"
    if b >= 1024:
        return f"{b / 1024:.0f} KB"
    return f"{b} B"


# ---------------------------------------------------------------------------
# Tree printer
# ---------------------------------------------------------------------------

def print_tree(node, max_depth=3, depth=0):
    msg = node["message"][:200]
    dur = node["duration_msec"]
    n_children = len(node.get("children", []))
    print(f"{'  ' * depth}[{fmt_duration(dur)}] ({n_children}ch) {msg}")
    if depth < max_depth:
        for c in node.get("children", []):
            print_tree(c, max_depth, depth + 1)


# ---------------------------------------------------------------------------
# Node finder
# ---------------------------------------------------------------------------

KEY_PATTERNS = [
    "fetch unique",
    "fetch matching series",
    "rollup ",
    "parallel process",
    "samplesScanned",
    "aggregate ",
    "binary op",
    "transform ",
    "merge series",
    "rollup cache",
    "cannot store",
    "the rollup evaluation",
    "eval: query=",
    "eval count",
    "sort series",
    "generate /api/",
]


def find_nodes(node, patterns, results, path="root"):
    msg = node.get("message", "")
    for p in patterns:
        if p in msg:
            results.append({
                "pattern": p,
                "duration_msec": node["duration_msec"],
                "message": msg,
                "path": path,
            })
            break  # match first pattern only to avoid duplicates
    for i, c in enumerate(node.get("children", [])):
        find_nodes(c, patterns, results, f"{path}/{i}")


# ---------------------------------------------------------------------------
# RPC breakdown extractor
# ---------------------------------------------------------------------------

def find_fetch_groups(node, groups, parent_label=""):
    """Find 'fetch matching series' nodes and collect their RPC children."""
    msg = node.get("message", "")
    if "fetch matching series" in msg:
        label = msg[:200]
        rpcs = []
        collect_rpcs(node, rpcs)

        # Also find the 'fetch unique' sibling/child summary
        fetch_unique = find_first(node, "fetch unique")
        groups.append({
            "label": label,
            "duration_msec": node["duration_msec"],
            "rpcs": rpcs,
            "fetch_unique": fetch_unique,
        })
        return  # don't recurse further inside this fetch
    for c in node.get("children", []):
        find_fetch_groups(c, groups, parent_label)


def collect_rpcs(node, rpcs):
    msg = node.get("message", "")
    if msg.startswith("rpc at vmstorage"):
        hostname = msg.split("rpc at vmstorage ")[-1].split(":")[0] if "rpc at vmstorage " in msg else "unknown"
        sent_msg = ""
        for c in node.get("children", []):
            cmsg = c.get("message", "")
            if "sent " in cmsg:
                sent_msg = cmsg
        rpcs.append({
            "hostname": hostname,
            "duration_msec": node["duration_msec"],
            "sent": sent_msg,
        })
        return
    for c in node.get("children", []):
        collect_rpcs(c, rpcs)


def find_first(node, pattern):
    msg = node.get("message", "")
    if pattern in msg:
        return {"duration_msec": node["duration_msec"], "message": msg}
    for c in node.get("children", []):
        r = find_first(c, pattern)
        if r:
            return r
    return None


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def parse_root_info(data):
    msg = data["message"]
    info = {"total_duration_msec": data["duration_msec"]}

    # Detect mode and extract version from the component prefix before the first ": "
    # Cluster: "vmselect-<version>: /select/..."
    # Single-node: "victoria-metrics-<version>: /api/v1/..."
    prefix = msg.split(": ", 1)[0] if ": " in msg else ""
    if "/select/" in msg:
        info["mode"] = "cluster"
        info["version"] = prefix
    else:
        info["mode"] = "single-node"
        info["version"] = prefix

    semver = extract_semver(prefix)
    if semver:
        info["semver"] = f"v{semver[0]}.{semver[1]}.{semver[2]}"

    # Endpoint
    if "/api/v1/query_range" in msg:
        info["endpoint"] = "query_range"
    elif "/api/v1/query" in msg:
        info["endpoint"] = "query"
    else:
        info["endpoint"] = "unknown"

    # Query
    m = re.search(r'query="(.+)"', msg)
    if m:
        info["query"] = m.group(1)

    # series count from end of message
    m = re.search(r'series=(\d+)\s*$', msg)
    if m:
        info["result_series"] = int(m.group(1))

    # start/end/step
    m = re.search(r'start=(\d+)', msg)
    if m:
        info["start"] = int(m.group(1))
    m = re.search(r'end=(\d+)', msg)
    if m:
        info["end"] = int(m.group(1))
    m = re.search(r'step=(\d+)', msg)
    if m:
        info["step"] = int(m.group(1))

    return info


def print_summary(data):
    info = parse_root_info(data)

    print("=" * 70)
    print("ROOT INFO")
    print("=" * 70)
    print(f"  Mode:           {info.get('mode', '?')}")
    version_line = info.get('version', '?')
    if info.get('semver'):
        version_line += f" (semver: {info['semver']})"
    print(f"  Version:        {version_line}")
    print(f"  Endpoint:       {info.get('endpoint', '?')}")
    print(f"  Total duration: {fmt_duration(info['total_duration_msec'])}")
    if "query" in info:
        q = info["query"]
        if len(q) > 300:
            q = q[:300] + "..."
        print(f"  Query:          {q}")
    if "start" in info and "end" in info:
        print(f"  Start:          {info['start']}")
        print(f"  End:            {info['end']}")
    if "step" in info:
        print(f"  Step:           {info['step']}ms")
    if "result_series" in info:
        print(f"  Result series:  {info['result_series']}")
    print()

    # Top-level tree (depth 3)
    print("=" * 70)
    print("TRACE TREE (depth 3)")
    print("=" * 70)
    print_tree(data, max_depth=3)
    print()

    # Key nodes
    print("=" * 70)
    print("KEY NODES (duration > 0.1ms)")
    print("=" * 70)
    results = []
    find_nodes(data, KEY_PATTERNS, results)
    for r in results:
        if r["duration_msec"] < 0.1:
            continue
        msg = r["message"]
        if len(msg) > 300:
            msg = msg[:300] + "..."
        print(f"  [{fmt_duration(r['duration_msec'])}] {msg}")
    print()

    # RPC / storage node breakdown
    print("=" * 70)
    print("FETCH / STORAGE NODE BREAKDOWN")
    print("=" * 70)
    groups = []
    find_fetch_groups(data, groups)
    for g in groups:
        label = g["label"]
        if len(label) > 150:
            label = label[:150] + "..."
        print(f"\n  Fetch: [{fmt_duration(g['duration_msec'])}] {label}")
        if g["fetch_unique"]:
            fu = g["fetch_unique"]
            print(f"  Summary: [{fmt_duration(fu['duration_msec'])}] {fu['message'][:250]}")
        rpcs = g["rpcs"]
        print(f"  Storage nodes: {len(rpcs)}")
        # Sort by duration desc, show top 5 and bottom 2
        rpcs_sorted = sorted(rpcs, key=lambda x: x["duration_msec"], reverse=True)
        if len(rpcs_sorted) <= 10:
            for r in rpcs_sorted:
                print(f"    {r['hostname'][:50]:50s} {fmt_duration(r['duration_msec']):>10s}  {r['sent']}")
        else:
            print(f"  Top 5 slowest:")
            for r in rpcs_sorted[:5]:
                print(f"    {r['hostname'][:50]:50s} {fmt_duration(r['duration_msec']):>10s}  {r['sent']}")
            print(f"  Bottom 2 fastest:")
            for r in rpcs_sorted[-2:]:
                print(f"    {r['hostname'][:50]:50s} {fmt_duration(r['duration_msec']):>10s}  {r['sent']}")
    print()

    # Computed totals
    print("=" * 70)
    print("COMPUTED TOTALS")
    print("=" * 70)
    total_bytes = 0
    total_samples_scanned = 0
    total_samples_fetched = 0
    total_series = 0

    for r in results:
        msg = r["message"]
        # fetch unique series=N, blocks=N, samples=N, bytes=N
        m = re.search(r"fetch unique series=(\d+), blocks=\d+, samples=(\d+), bytes=(\d+)", msg)
        if m:
            total_series += int(m.group(1))
            total_samples_fetched += int(m.group(2))
            total_bytes += int(m.group(3))
        # samplesScanned=N
        m = re.search(r"samplesScanned=(\d+)", msg)
        if m:
            total_samples_scanned += int(m.group(1))

    print(f"  Total unique series fetched: {total_series:,}")
    print(f"  Total samples fetched:       {total_samples_fetched:,}")
    print(f"  Total samples scanned:       {total_samples_scanned:,}")
    print(f"  Total bytes transferred:     {fmt_bytes(total_bytes)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    trace_path = sys.argv[1]
    data = load_trace(trace_path)

    cmd = sys.argv[2] if len(sys.argv) > 2 else "summary"

    if cmd == "summary":
        print_summary(data)

    elif cmd == "tree":
        depth = 3
        for i, arg in enumerate(sys.argv[3:]):
            if arg == "--depth" and i + 1 < len(sys.argv) - 3:
                depth = int(sys.argv[3 + i + 1])
        print_tree(data, max_depth=depth)

    elif cmd == "nodes":
        pattern = None
        for i, arg in enumerate(sys.argv[3:]):
            if arg == "--pattern" and i + 1 < len(sys.argv) - 3:
                pattern = sys.argv[3 + i + 1]
        if not pattern:
            print("Usage: parse_trace.py <file> nodes --pattern <substring>")
            sys.exit(1)
        results = []
        find_nodes(data, [pattern], results)
        for r in results:
            msg = r["message"]
            if len(msg) > 400:
                msg = msg[:400] + "..."
            print(f"[{fmt_duration(r['duration_msec'])}] {msg}")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
