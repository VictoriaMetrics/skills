---
name: victoriametrics-docs
description: >
  Look up VictoriaMetrics, VictoriaLogs, VictoriaTraces, operator, vmanomaly, Helm chart and
  VictoriaMetrics Cloud documentation before naming a command-line flag, an HTTP API path, or a
  LogsQL/MetricsQL construct. Use when about to state that a flag or endpoint exists, when a
  user asks what a flag does, or when a previous answer may have invented an API path. Triggers
  on: command-line flag, CLI flag, what flag, flag does, API path, HTTP endpoint, does this
  endpoint exist, MetricsQL function, LogsQL pipe, LogsQL filter, operator flag, is this
  documented, where are the docs, VictoriaMetrics documentation.
allowed-tools: Bash(python3:*), Read
---

# VictoriaMetrics documentation lookup

Confirm a flag, an API path or a query construct against the published documentation before
naming it. An invented flag reads exactly like a real one, so a reader cannot tell the
difference without checking.

## Critical rules

- Check before you name. Do not write a flag or an endpoint and then verify it.
- `NOT FOUND` is an answer. Report that the term is undocumented. The lookup may list similar
  documented terms under it. Each one is a different term: name it as a correction only with
  its own citation, and never present it as the term the user asked about.
- `UNKNOWN` is not an answer. Some pages, or the page index, did not load, so the term may be
  on one of them. Investigate before you answer: check that docs.victoriametrics.com is
  reachable and run the lookup again. If only some pages fail, open those pages directly; the
  script lists each one with its error. Never report the term as undocumented.
- `NOT FOUND` with a topic covers only that section. Before you call a term undocumented,
  make sure the topic was right, or run the lookup again without one.
- Quote the lines the lookup printed, and cite the link above them. That link carries the
  section anchor, so it opens at the section the claim came from. A claim without it is a
  guess. Do not cite a bare page URL when the lookup gave you an anchored one.
- `/flags` on a running instance is not a list of available flags. It returns only the flags an
  operator set explicitly, so it answers how this instance is configured and nothing more.
- A skill that already carries an API reference wins for its own endpoints. Use this one for
  flags, for products those skills do not cover, and for anything their reference omits.

## Usage

`find` prints the lines that contain a term, one quote per section, under a link to that
section. `topics` lists the sections a lookup can be limited to.

```bash
# Which sections can a lookup be limited to?
python3 <skill_base_dir>/scripts/vmdocs.py topics

# Does this flag exist, and what does it do?
python3 <skill_base_dir>/scripts/vmdocs.py find "-retentionPeriod"

# Does this API path exist?
python3 <skill_base_dir>/scripts/vmdocs.py find "/select/logsql/hits"

# A LogsQL pipe, limited to the VictoriaLogs section
python3 <skill_base_dir>/scripts/vmdocs.py find "block_stats" "victorialogs"

# Show up to 10 sections instead of 3
python3 <skill_base_dir>/scripts/vmdocs.py find --sections 10 -- "extra_filters" "victorialogs"

# Show up to 5 matching lines in each section instead of 1, without the lines around them
python3 <skill_base_dir>/scripts/vmdocs.py find --per-section 5 -- "-retentionPeriod" "victorialogs"
```

Options go before `--`. Without `--` every argument is the term or the topic, so a term that
starts with `-`, such as `-retentionPeriod` or `--sections`, needs no escaping.

A topic must be a name that `topics` prints, such as `victorialogs` or `operator`. Any other
topic exits 2 and prints the list, so never guess one.

A term starting with `-` or `/` is treated as a flag or an API path. Every page of the topic, or
of the whole site without one, is searched before the lookup says `NOT FOUND`.

Many flags exist in more than one product. Pass the product's section as the topic to check
one of them, or the VictoriaMetrics pages, which come first, fill the output:

```bash
python3 <skill_base_dir>/scripts/vmdocs.py find "-storageNode" "victorialogs"
```

Terms match whole. `-search.maxUnique` does not match `-search.maxUniqueTimeseries`, so a
truncated or invented name stays `NOT FOUND`. Flags and paths also match case: `-storagenode`
is not `-storageNode`. For a flag or a path, up to three similar documented terms follow, with
citations: longer terms that start with the input first, then near spellings.

A path still matches when the page prints it with a routing prefix or a sub-path. When the
path on the page is longer than the term, a `matched in` line shows it, so `/query` found
inside `/api/v1/query` reads as that path and not as an endpoint of its own.

A definition comes before mentions: a flag in a flags section such as `#common-flags`, or a
section named after the term, such as `#rate` or `#stats-pipe`.

Exit code 1 with `NOT FOUND` means the term does not appear in the documentation.
Exit code 2 means a usage error, such as a topic that `topics` does not list.
Exit code 3 with `UNKNOWN` means some pages could not be fetched, so the lookup
cannot prove the term is absent. The script lists the pages that failed.

## Reading the output

A hit is a link to the section, then one matching line in it with one line on each side: the
definition when the section has one, otherwise the first match. A flag definition starts at the
flag line, because the line above it describes the previous flag. When the section has more
matching lines, a count follows the quote with the command that shows them. Cite the link, quote
the lines (long lines shortened here):

```
$ vmdocs.py find "-retentionPeriod" victorialogs
https://docs.victoriametrics.com/victorialogs/#common-flags
-retentionPeriod value
Log entries with timestamps older than now-retentionPeriod are automatically deleted; ...
```

When the term is in more sections than were shown, the last lines say so. Do not treat the
shown sections as everything:

```
Showing 3 of 7 sections (12 matching lines on 4 pages).
The term is also in the sections not shown. To see them, run: vmdocs.py find --sections 7 --per-section 1 -- -retentionPeriod victorialogs
```

A miss states what was searched, then any close documented terms. Each is a different term:

```
$ vmdocs.py find "-retentionPeriods" victorialogs
NOT FOUND: -retentionPeriods is on none of the 39 pages of the victorialogs section.
Similar documented terms, each a different term:
-retentionPeriod https://docs.victoriametrics.com/victorialogs/#common-flags
```

A failure says the answer is unknown, what to do, and which pages failed with which error:

```
UNKNOWN: 15 of 15 pages could not be fetched, and the term may be on one of them.
Do not report the term as undocumented. Check that docs.victoriametrics.com is
reachable, then run the lookup again. If only some pages fail, open them directly.
https://docs.victoriametrics.com/victoriatraces/  (HTTP Error 503: Service Unavailable)
```

## To answer a question

The script matches terms, not questions. Turn the question into the terms it depends on:

1. Pick the literal terms: flags, HTTP paths, component names, LogsQL or MetricsQL keywords.
2. Run `find` for each term, with the product's section from `topics` when the question
   names a product.
3. Answer only from the lines the lookup printed, and cite the link above each one. A term
   that comes back `NOT FOUND` is not part of the answer.

## What the script does

It reads `https://docs.victoriametrics.com/llms.txt`, the published index of documentation pages,
and adds the pages that only `sitemap.xml` lists, such as the VictoriaLogs and VictoriaTraces root
pages. It loads those pages in parallel, converts them to text and prints the matching lines
with one line of context. A lookup stops loading after 90 seconds and reports the pages it did
not reach as `UNKNOWN`, so it always answers inside an agent's shell time limit. Each hit is
printed under the link to the section it came from, built from the heading anchor above the
match. Text above the first heading has no anchor, so its hit carries
the bare page URL.

Fetched pages are cached under the system temporary directory, per user, for six hours, so the first lookup
is slow and later ones are fast. Nothing is written into the repository or the user's project.

Standard library only. No installation step.

## What it is good for

Flags, HTTP API paths and MetricsQL/LogsQL constructs, across VictoriaMetrics, VictoriaLogs,
VictoriaTraces, the operator, vmanomaly, the Helm charts and VictoriaMetrics Cloud. A term matches whole, so a truncated or invented name stays `NOT FOUND` and is
not confirmed by a longer real one.

## Limits

- The lookup needs network access to `docs.victoriametrics.com`.
- It reports what the published documentation says. Where the documentation is wrong or
  incomplete, so is the answer.
- It searches the current documentation, which describes the latest release. An older instance
  may not have a flag the lookup finds.
- A cached page can be up to six hours old.
