#!/usr/bin/env python3
"""Look up VictoriaMetrics documentation. Standard library only.

Commands:
  topics                  list the documentation sections a lookup can be limited to
  find TERM [TOPIC] [--limit N]
                          print the lines that contain the term, one per section,
                          with section links; N sections at most (default 3)

Pages come from https://docs.victoriametrics.com/llms.txt and the sitemap.

Exit code 1 and "NOT FOUND" mean the term is absent from the documentation. Treat
that as the answer, not as a failure to look. For a flag or a path, the lines after
"NOT FOUND" name documented terms close to it; each is a different term.

Exit code 2 means a usage error, such as a topic that `topics` does not list.
Exit code 3 and "UNKNOWN" mean some pages could not be fetched, so absence is not
proven.
"""

import concurrent.futures
import difflib
import functools
import hashlib
import html
import http.client
import os
import re
import stat
import sys
import tempfile
import time
import urllib.request

LLMS_INDEX = "https://docs.victoriametrics.com/llms.txt"
SITEMAP = "https://docs.victoriametrics.com/sitemap.xml"
# Per user: /tmp is shared on Linux.
CACHE_DIR = os.path.join(tempfile.gettempdir(), "vmdocs-cache-%s" % getattr(os, "getuid", lambda: "")())
CACHE_MAX_AGE = 6 * 60 * 60  # documentation changes on release, not by the minute
# A cold miss took 2 min one page at a time, 17 s with eight in parallel.
FETCH_WORKERS = 8
# An agent's shell call is killed at 120 s; answer UNKNOWN before that.
TIME_BUDGET_SECONDS = 90
PAGE_TIMEOUT_SECONDS = 15
HITS_SHOWN = 3
SUGGESTIONS = 3
# IncompleteRead is not an OSError.
FETCH_ERRORS = (OSError, http.client.HTTPException)

ENTRY_RE = re.compile(r"- \[(.+?)\]\((.+?)\): (.*)")

# Whole terms only, or "-search.maxUnique" matches "-search.maxUniqueTimeseries".
# Paths allow a routing prefix (/prometheus/api/v1/...) on the left.
FLAG_SHAPE = r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_-])(?!\.[A-Za-z0-9_])"
PATH_SHAPE = r"%s(?![A-Za-z0-9_-])"
WORD_SHAPE = r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])"

FLAG_TOKEN = r"(?<![\w.-])-[A-Za-z][\w.]*"
PATH_TOKEN = r"(?<![\w./:-])/[\w./-]+"
# A one-letter typo scores 0.98; an unrelated flag with the same prefix, 0.68.
SUGGEST_CUTOFF = 0.8

DEADLINE = time.monotonic() + TIME_BUDGET_SECONDS


def cache_dir():
    # Another user could create it first and plant fake pages.
    os.makedirs(CACHE_DIR, mode=0o700, exist_ok=True)
    info = os.lstat(CACHE_DIR)
    if not stat.S_ISDIR(info.st_mode) or (hasattr(os, "getuid") and info.st_uid != os.getuid()):
        raise PermissionError("%s is not a directory you own; remove it and run again" % CACHE_DIR)
    return CACHE_DIR


def read_cache(path):
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) >= CACHE_MAX_AGE:
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_cache(path, body):
    # Atomic, so an interrupted write never leaves a truncated page in the cache.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, path)


def download(url):
    remaining = DEADLINE - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("the %d s time budget of the lookup is spent" % TIME_BUDGET_SECONDS)
    with urllib.request.urlopen(url, timeout=min(PAGE_TIMEOUT_SECONDS, remaining)) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch(url):
    path = os.path.join(cache_dir(), hashlib.sha1(url.encode()).hexdigest())
    body = read_cache(path)
    if body is None:
        body = download(url)
        write_cache(path, body)
    return body


# Hugo minifies the pages, so heading ids arrive unquoted: <h2 id=retention>.
HEADING_RE = re.compile(r"""<h[1-6][^>]*\bid=["']?([^"'\s>]+)["']?[^>]*>""", re.I)
ANCHOR_MARK = "@@section@@"


def to_text(page):
    match = (re.search(r"<main\b.*?</main>", page, re.S)
             or re.search(r"<article\b.*?</article>", page, re.S))
    body = match.group(0) if match else page
    # The table of contents is an <aside> inside <main>.
    body = re.sub(r"<(script|style|nav|svg|aside)\b.*?</\1>", "", body, flags=re.S)
    body = HEADING_RE.sub(lambda mt: "\n" + ANCHOR_MARK + mt.group(1) + "\n", body)
    # Without this a whole flag list collapses onto one line.
    body = re.sub(r"(?i)</(p|li|h[1-6]|div|tr|td|th|pre|blockquote|table|ul|ol|section|dt|dd)\s*>", "\n", body)
    body = re.sub(r"(?i)<(br|hr)\s*/?>", "\n", body)
    text = html.unescape(re.sub(r"<[^>]+>", "", body))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    sections, anchor = [], ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(ANCHOR_MARK):
            anchor = line[len(ANCHOR_MARK):].strip()
            continue
        sections.append((anchor, line))
    return sections


@functools.lru_cache(maxsize=None)
def page_text(url):
    return to_text(fetch(url))


def llms_entries(text):
    return [m.groups() for m in map(ENTRY_RE.match, text.splitlines()) if m]


def sitemap_entries(text, known):
    urls = dict.fromkeys(re.findall(r"<loc>([^<]+)</loc>", text))
    return [(url_path(url), url, "") for url in urls if url not in known]


def load_index():
    # llms.txt misses pages, including the product root pages; the sitemap has them.
    entries = llms_entries(fetch(LLMS_INDEX))
    try:
        sitemap = fetch(SITEMAP)
    except FETCH_ERRORS as e:
        print("warning: cannot fetch %s: %s" % (SITEMAP, reason(e)), file=sys.stderr)
        return entries, False
    return entries + sitemap_entries(sitemap, {url for _, url, _ in entries}), True


def url_path(url):
    return url.split("docs.victoriametrics.com", 1)[-1]


def is_root(url):
    return url.rstrip("/").count("/") == 3


def roots_first(entries):
    # A product root page holds most flags and endpoints, so it is cited first.
    return sorted(entries, key=lambda e: not is_root(e[1]))


def section(url):
    return url_path(url).strip("/").split("/")[0]


def topics(entries):
    counts = {}
    for _, url, _ in entries:
        name = section(url)
        if name:
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items())


def section_pages(entries, topic):
    return [e for e in entries if section(e[1]) == topic]


def is_flag_or_path(term):
    return term.startswith(("-", "/"))


def term_pattern(term):
    # Flags and paths are case-sensitive in every component.
    if term.startswith("-"):
        return re.compile(FLAG_SHAPE % re.escape(term))
    if term.startswith("/"):
        return re.compile(PATH_SHAPE % re.escape(term))
    return re.compile(WORD_SHAPE % re.escape(term), re.I)


def is_definition(term, anchor, line):
    """A flag in a flags section, or a section named after the term."""
    if term.startswith("-"):
        return "flags" in anchor and re.match(r"\s*%s(\s|$)" % re.escape(term), line) is not None
    if term.startswith("/"):
        return False
    slug = re.sub(r"\s+", "-", term.lower())
    return anchor in (slug, slug + "-pipe", slug + "-filter")


def matched_path(term, line):
    # Shows /query found inside /api/v1/query as that longer path.
    token = re.search(r"[\w./-]*%s[\w./-]*" % re.escape(term), line).group(0)
    return token.rstrip(".")


def page_hits(term, pattern, url, sections, context):
    for n, (anchor, line) in enumerate(sections):
        if not pattern.search(line):
            continue
        definition = is_definition(term, anchor, line)
        # In a flag list the line above a flag describes the previous flag.
        before = 0 if definition and term.startswith("-") else context
        quote = "\n".join(t for a, t in sections[max(0, n - before):n + context + 1] if a == anchor)
        cite = url + "#" + anchor if anchor else url
        if term.startswith("/") and matched_path(term, line) != term:
            cite += "\nmatched in " + matched_path(term, line)
        yield definition, cite, quote


def find(term, pages, context=1, skip=()):
    """Every section that contains the term, definitions first, as
    (is_definition, cite, first quote, matching lines) tuples."""
    pattern = term_pattern(term)
    definitions, mentions, failed = [], [], []
    for _, url, _ in pages:
        if url in skip:
            failed.append((url, skip[url]))
            continue
        try:
            sections = page_text(url)
        except FETCH_ERRORS as e:
            failed.append((url, reason(e)))
            continue
        for hit in page_hits(term, pattern, url, sections, context):
            (definitions if hit[0] else mentions).append(hit)
    return by_section(definitions + mentions), failed


def by_section(hits):
    # One quote per section, so one long section cannot fill the output and hide other pages.
    groups = {}
    for is_def, cite, quote in hits:
        link = cite.split("\n", 1)[0]
        if link in groups:
            groups[link][3] += 1
        else:
            groups[link] = [is_def, cite, quote, 1]
    return [tuple(g) for g in groups.values()]


def reason(error):
    return str(error) or type(error).__name__


def prefetch(pages):
    def load(url):
        try:
            fetch(url)
        except FETCH_ERRORS as e:
            return url, reason(e)
        return None
    with concurrent.futures.ThreadPoolExecutor(FETCH_WORKERS) as pool:
        return dict(r for r in pool.map(load, [url for _, url, _ in pages]) if r)


def documented_terms(term, pages):
    shape = FLAG_TOKEN if term.startswith("-") else PATH_TOKEN
    terms = set()
    for _, url, _ in pages:
        try:
            sections = page_text(url)
        except FETCH_ERRORS:
            continue
        for _, line in sections:
            terms.update(t.rstrip("./-") for t in re.findall(shape, line))
    return terms


def suggest(term, pages, limit=SUGGESTIONS):
    # A truncated name is the usual mistake, and similarity ranks it too low.
    low = term.lower()
    extend, similar = [], []
    for t in sorted(documented_terms(term, pages)):
        if t == term:
            continue
        if t.lower().startswith(low):
            extend.append(t)
        else:
            ratio = difflib.SequenceMatcher(None, low, t.lower()).ratio()
            if ratio >= SUGGEST_CUTOFF:
                similar.append((-ratio, t))
    ranked = sorted(extend, key=len) + [t for _, t in sorted(similar)]
    found = []
    for t in ranked[:limit]:
        hits, _ = find(t, pages)
        if hits:
            found.append((t, hits[0][1]))
    return found


def report_hits(hits, limit, topic=None):
    for _, cite, quote, lines in hits[:limit]:
        print(cite)
        print(quote)
        if lines > 1:
            print("(%d more matching lines in this section)" % (lines - 1))
        print()
    if len(hits) > limit:
        pages = {cite.split("#")[0].split("\n")[0] for _, cite, _, _ in hits}
        print("Showing %d of %d sections (%d matching lines on %d pages)."
              % (limit, len(hits), sum(h[3] for h in hits), len(pages)))
        print("The term is also in the sections not shown. Run again with --limit N to see them%s."
              % ("" if topic else ", or with a topic to search one product"))
    return 0


def report_not_found(term, where, count, close):
    print("NOT FOUND: %s is on none of the %d pages of %s." % (term, count, where))
    if close:
        print("Similar documented terms, each a different term:")
    for t, cite in close:
        print(t, cite)
    return 1


def report_unfetched(failed, count):
    print("UNKNOWN: %d of %d pages could not be fetched, and the term may be on one of them."
          % (len(failed), count))
    print("Do not report the term as undocumented. Check that docs.victoriametrics.com is")
    print("reachable, then run the lookup again. If only some pages fail, open them directly.")
    for url, why in failed:
        print("%s  (%s)" % (url, why))
    return 3


def report_incomplete_index():
    print("UNKNOWN: sitemap.xml could not be fetched, so the pages and sections only it lists")
    print("were not searched. Do not report the term or topic as missing. Check that")
    print("docs.victoriametrics.com is reachable, then run the lookup again.")
    return 3


def report_no_index(error):
    print("UNKNOWN: cannot fetch the documentation index: %s" % reason(error))
    print("Nothing was searched. Do not report the term as undocumented.")
    print("Check that docs.victoriametrics.com is reachable, then run the lookup again.")
    return 3


def report_unknown_topic(topic, names):
    print("unknown topic: %s" % topic)
    print("Pick one of these and run the lookup again, or leave the topic out:")
    print(", ".join(names))
    return 2


def cmd_topics():
    entries, complete = load_index()
    if not complete:
        return report_incomplete_index()
    for name, count in topics(entries):
        print("%s (%d pages)" % (name, count))
    return 0


def cmd_find(term, topic, limit):
    entries, complete = load_index()
    if topic:
        names = [name for name, _ in topics(entries)]
        if topic not in names:
            return report_incomplete_index() if not complete else report_unknown_topic(topic, names)
        entries = roots_first(section_pages(entries, topic))
    hits, failed = find(term, entries, skip=prefetch(entries))
    if hits:
        return report_hits(hits, limit, topic)
    if failed:
        return report_unfetched(failed, len(entries))
    if not complete:
        return report_incomplete_index()
    close = suggest(term, entries) if is_flag_or_path(term) else []
    where = "the %s section" % topic if topic else "the documentation"
    return report_not_found(term, where, len(entries), close)


def take_limit(args):
    """Removes --limit N from args; returns N, the default, or None if N is invalid."""
    if "--limit" not in args:
        return HITS_SHOWN
    i = args.index("--limit")
    value = args[i + 1] if i + 1 < len(args) else ""
    del args[i:i + 2]
    try:
        limit = int(value)
    except ValueError:
        return None
    return limit if limit > 0 else None


def dispatch(argv):
    args = argv[1:]
    limit = take_limit(args)
    if limit is None:
        print("--limit needs a positive whole number")
        return 2
    if args == ["topics"]:
        return cmd_topics()
    if len(args) < 2:
        print(__doc__)
        return 2
    command, term = args[0], args[1]
    if command == "find":
        return cmd_find(term, args[2] if len(args) > 2 else None, limit)
    print("unknown command: %s" % command)
    return 2


def main(argv):
    try:
        return dispatch(argv)
    except FETCH_ERRORS as e:
        return report_no_index(e)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
