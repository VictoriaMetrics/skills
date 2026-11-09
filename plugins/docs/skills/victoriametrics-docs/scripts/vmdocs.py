#!/usr/bin/env python3
"""Look up VictoriaMetrics documentation. Standard library only.

Commands:
  topics                  list the documentation sections a lookup can be limited to
  find [--sections N] [--per-section N] -- TERM [TOPIC]
  find TERM [TOPIC]       print the lines that contain the term under links to their
                          sections: N sections at most (default 3), N lines in each
                          (default 1). Options go before "--"; without "--" there are
                          none, so a term like "-retentionPeriod" needs no escaping.

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
import shlex
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
SECTIONS_SHOWN = 3
QUOTES_PER_SECTION = 1
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
    (is_definition, cite, quotes) tuples."""
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
    # Grouped by section, so one long section cannot fill the output and hide other pages.
    groups = {}
    for is_def, cite, quote in hits:
        link = cite.split("\n", 1)[0]
        _, _, quotes = groups.setdefault(link, (is_def, cite, []))
        quotes.append(quote)
    return list(groups.values())


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


def find_command(term, topic, max_sections, max_per_section):
    operands = [term, topic] if topic else [term]
    return "vmdocs.py find --sections %d --per-section %d -- %s" % (
        max_sections, max_per_section, shlex.join(operands))


def report_hits(hits, term, topic, max_sections, max_per_section):
    for _, cite, quotes in hits[:max_sections]:
        print(cite)
        print("\n".join(quotes[:max_per_section]))
        hidden = len(quotes) - max_per_section
        if hidden > 0:
            noun = "line" if hidden == 1 else "lines"
            print("(%d more matching %s in this section; to see them, run: %s)"
                  % (hidden, noun, find_command(term, topic, max_sections, len(quotes))))
        print()
    if len(hits) > max_sections:
        pages = {cite.split("#")[0].split("\n")[0] for _, cite, _ in hits}
        print("Showing %d of %d sections (%d matching lines on %d pages)."
              % (max_sections, len(hits), sum(len(quotes) for _, _, quotes in hits), len(pages)))
        print("The term is also in the sections not shown%s. To see them, run: %s"
              % ("" if topic else "; a topic limits the search to one product",
                 find_command(term, topic, len(hits), max_per_section)))
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


def cmd_find(term, topic, max_sections, max_per_section):
    entries, complete = load_index()
    if topic:
        names = [name for name, _ in topics(entries)]
        if topic not in names:
            return report_incomplete_index() if not complete else report_unknown_topic(topic, names)
        entries = roots_first(section_pages(entries, topic))
    # Several quotes with context lines would repeat the lines that nearby matches share.
    context = 1 if max_per_section == 1 else 0
    hits, failed = find(term, entries, context, skip=prefetch(entries))
    if hits:
        return report_hits(hits, term, topic, max_sections, max_per_section)
    if failed:
        return report_unfetched(failed, len(entries))
    if not complete:
        return report_incomplete_index()
    close = suggest(term, entries) if is_flag_or_path(term) else []
    where = "the %s section" % topic if topic else "the documentation"
    return report_not_found(term, where, len(entries), close)


def parse_options(args):
    """Splits args at "--" into options and operands, as POSIX utility syntax guideline 10
    says. Without "--" every argument is an operand. A repeated option takes the last value."""
    options = {"--sections": SECTIONS_SHOWN, "--per-section": QUOTES_PER_SECTION}
    if "--" not in args:
        return options, args
    i = args.index("--")
    given = iter(args[:i])
    for name in given:
        if name not in options:
            raise ValueError("unknown option: %s" % name)
        value = next(given, None)
        if value is None:
            raise ValueError("%s needs a value" % name)
        options[name] = positive_int(name, value)
    return options, args[i + 1:]


def positive_int(name, value):
    try:
        number = int(value)
    except ValueError:  # also raised for a number too long to convert
        number = 0
    if number < 1:
        raise ValueError("%s needs a positive whole number" % name)
    return number


def usage_error(message):
    print(message, file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


def dispatch(argv):
    args = argv[1:]
    if args in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    if args == ["topics"]:
        return cmd_topics()
    if not args:
        return usage_error("missing command")
    if args[0] != "find":
        return usage_error("unknown command: %s" % args[0])
    try:
        options, operands = parse_options(args[1:])
    except ValueError as e:
        return usage_error(str(e))
    if len(operands) not in (1, 2):
        return usage_error("find needs a term and at most one topic; options go before --")
    topic = operands[1] if len(operands) == 2 else None
    return cmd_find(operands[0], topic, options["--sections"], options["--per-section"])


def main(argv):
    try:
        return dispatch(argv)
    except FETCH_ERRORS as e:
        return report_no_index(e)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
