#!/usr/bin/env python3
"""
VictoriaMetrics changelog checker — finds performance-relevant changes in versions
newer than the one observed in a trace.

Usage:
    python3 check_changelog.py <version> <mode>

    version  — semver string, e.g. v1.130.0
    mode     — "cluster" or "single-node"

Example:
    python3 check_changelog.py v1.130.0 cluster
"""

import re
import sys
import urllib.request
import urllib.error
from datetime import date

CHANGELOG_BASE = (
    "https://raw.githubusercontent.com/VictoriaMetrics/VictoriaMetrics"
    "/master/docs/victoriametrics/changelog"
)

PERF_KEYWORDS = re.compile(
    r"latency|performance|speed|slow|memory usage|memory consumption"
    r"|cpu usage|cpu utilization|cache|optimize|reduce|faster|improve"
    r"|i/o|disk usage|allocations",
    re.IGNORECASE,
)

CLUSTER_COMPONENTS = re.compile(r"vmselect|vmstorage|vminsert", re.IGNORECASE)
SINGLE_COMPONENTS = re.compile(r"vmsingle|victoria-metrics", re.IGNORECASE)


def parse_version(version_str):
    """Parse 'v1.130.0' into (1, 130, 0). Returns None on failure."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", version_str)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def fetch_changelogs():
    """Fetch current and previous year changelog markdown files. Best-effort."""
    current_year = date.today().year
    urls = [
        f"{CHANGELOG_BASE}/CHANGELOG.md",
        f"{CHANGELOG_BASE}/CHANGELOG_{current_year - 1}.md",
    ]
    results = []
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                results.append(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            pass
    return results


def parse_changelog(markdown):
    """Parse changelog markdown into a list of version entries."""
    # Split by version headings: ## [vX.Y.Z](...)
    parts = re.split(r"^## \[v(\d+\.\d+\.\d+)\]", markdown, flags=re.MULTILINE)
    # parts[0] is preamble/tip, then alternating: version_str, body, version_str, body...
    versions = []
    i = 1
    while i + 1 < len(parts):
        ver_str = parts[i]
        body = parts[i + 1]
        i += 2

        ver = parse_version(ver_str)
        if not ver:
            continue

        # Skip stub entries ("See changes here")
        body_stripped = body.strip()
        if len(body_stripped) < 200 and "see changes" in body_stripped.lower():
            continue

        # Extract release date
        released = ""
        m = re.search(r"Released at (\d{4}-\d{2}-\d{2})", body)
        if m:
            released = m.group(1)

        # Extract FEATURE and BUGFIX entries
        entries = []
        for line in body.split("\n"):
            line = line.strip()
            if line.startswith("* FEATURE:") or line.startswith("* BUGFIX:"):
                entries.append(line)

        versions.append({
            "version": ver,
            "version_str": f"v{ver_str}",
            "released": released,
            "entries": entries,
        })

    return versions


def is_component_relevant(entry, mode):
    """Check if a changelog entry is relevant to the given mode."""
    if mode == "cluster":
        # Relevant if it mentions cluster components or is general
        if CLUSTER_COMPONENTS.search(entry):
            return True
        # Also relevant if it mentions vmsingle (shared code paths)
        if SINGLE_COMPONENTS.search(entry):
            return True
        # General entries (no specific component after FEATURE:/BUGFIX:) are relevant
        m = re.match(r"\* (?:FEATURE|BUGFIX):\s*\[?(\w+)", entry)
        if m:
            component = m.group(1).lower()
            # If it's a specific unrelated component, skip
            if component in ("vmagent", "vmalert", "vmauth", "vmctl",
                             "vmbackup", "vmrestore", "vmbackupmanager",
                             "vmui", "dashboards", "vmgateway"):
                return False
        return True
    else:
        # Single-node mode
        if SINGLE_COMPONENTS.search(entry):
            return True
        m = re.match(r"\* (?:FEATURE|BUGFIX):\s*\[?(\w+)", entry)
        if m:
            component = m.group(1).lower()
            if component in ("vmagent", "vmalert", "vmauth", "vmctl",
                             "vmbackup", "vmrestore", "vmbackupmanager",
                             "vmui", "dashboards", "vmgateway",
                             "vminsert"):
                return False
        return True


def filter_relevant(all_versions, trace_version, mode):
    """Filter to newer versions with performance-relevant entries."""
    results = []
    for v in all_versions:
        if v["version"] <= trace_version:
            continue
        relevant = [
            e for e in v["entries"]
            if PERF_KEYWORDS.search(e) and is_component_relevant(e, mode)
        ]
        if relevant:
            results.append({
                "version_str": v["version_str"],
                "version": v["version"],
                "released": v["released"],
                "entries": relevant,
            })
    # Sort by version ascending
    results.sort(key=lambda x: x["version"])
    return results


def clean_entry(entry):
    """Strip markdown links and truncate for display."""
    # Remove markdown links: [text](url) -> text
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", entry)
    # Remove leading "* "
    cleaned = re.sub(r"^\* ", "", cleaned)
    if len(cleaned) > 200:
        cleaned = cleaned[:200] + "..."
    return cleaned


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    version_str = sys.argv[1]
    mode = sys.argv[2]

    if mode not in ("cluster", "single-node"):
        print(f"Error: mode must be 'cluster' or 'single-node', got '{mode}'")
        sys.exit(1)

    trace_version = parse_version(version_str)
    if not trace_version:
        print(f"Error: cannot parse version '{version_str}'")
        sys.exit(1)

    print(f"Fetching VictoriaMetrics changelogs...")
    changelogs = fetch_changelogs()
    if not changelogs:
        print("Warning: could not fetch any changelog files (network issue?)")
        sys.exit(0)

    # Parse and merge all changelog entries, dedup by version
    all_versions = {}
    for md in changelogs:
        for v in parse_changelog(md):
            key = v["version"]
            if key not in all_versions:
                all_versions[key] = v

    filtered = filter_relevant(list(all_versions.values()), trace_version, mode)

    print("=" * 70)
    print(f"CHANGELOG: PERFORMANCE-RELEVANT CHANGES SINCE {version_str}")
    print("=" * 70)

    if not filtered:
        print("  No performance-relevant changes found in newer versions.")
    else:
        for v in filtered:
            released = f" (released {v['released']})" if v["released"] else ""
            print(f"\n  {v['version_str']}{released}:")
            for e in v["entries"]:
                print(f"    - {clean_entry(e)}")
    print()


if __name__ == "__main__":
    main()
