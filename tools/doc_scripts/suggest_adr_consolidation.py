#!/usr/bin/env python3
"""Lists decision records that may be worth condensing, merging or demoting
(ADR 0037 revision 4). Advisory: it prints candidates and changes nothing, and
what a hit means is the maintainer's call.

Signals, each read from the docs and no more:

- **Implementation detail**: an accepted Decision that names many files, which
  reads like a change record that belongs in a topic doc.
- **Similar problems**: lineages whose title, summary and Problem share many
  words, which may be one problem stated for different cases.
- **Tight clusters**: three or more lineages of one topic that all list one
  another in `related:`, which may be one decision split in pieces.

  --report   also print the quarterly report: open explorations that have
             stood still, `working` revisions untouched for a long time, and
             whether too many projects are active.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from itertools import combinations
from pathlib import Path

from doc_scripts.doc_explorations import last_commit_date, stale_warnings
from doc_scripts.doc_frontmatter import ROOT, Lineage, load_lineages
from doc_scripts.doc_frozen import split
from doc_scripts.generate_doc_indexes import active_project_warnings

# A Decision that names at least this many files is reported as implementation detail.
FILE_REFERENCE_LIMIT = 8
# Two records whose title, summary and Problem share at least this fraction of their words are reported as similar.
# Older records have no Problem section, so the title and summary carry them.
SIMILARITY_LIMIT = 0.19
# A `working` revision untouched for this many days is reported in the quarterly report.
WORKING_STALE_DAYS = 90

_FILE_RE = re.compile(r"`[\w./-]+\.(?:py|yml|yaml|sh|md|j2|hcl|tf|toml|json)`")
_WORD_RE = re.compile(r"[a-z]{4,}")
_STOP = {
    "that", "this", "with", "from", "have", "what", "which", "when", "than", "then", "there", "their", "they", "them", "does",
    "into", "only", "also", "each", "every", "must", "should", "would", "could", "been", "being", "were", "will", "your", "about",
    "true", "stated", "given", "while", "where", "whose", "without", "independent", "solution", "problem",
}  # fmt: skip


def section(body: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", body, re.DOTALL | re.MULTILINE)
    return m.group(1) if m else ""


def _body(rev) -> str:
    return split(rev.path.read_text(encoding="utf-8"))[1]


def _words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP}


def _record_words(lineage: Lineage) -> set[str]:
    rev = lineage.current()
    return _words(f"{rev.fm['title']} {rev.fm['summary']} {section(_body(rev), 'Problem')}")


def implementation_detail(lineages: list[Lineage]) -> list[tuple[str, int]]:
    found = []
    for lineage in lineages:
        rev = lineage.current()
        if rev.status != "accepted":
            continue
        count = len(set(_FILE_RE.findall(section(_body(rev), "Decision"))))
        if count >= FILE_REFERENCE_LIMIT:
            found.append((lineage.id, count))
    return sorted(found, key=lambda item: -item[1])


def similar_problems(lineages: list[Lineage]) -> list[tuple[str, str, float]]:
    problems = {lineage.id: _record_words(lineage) for lineage in lineages}
    found = []
    for (a, words_a), (b, words_b) in combinations(sorted(problems.items()), 2):
        union = words_a | words_b
        if union and len(words_a & words_b) / len(union) >= SIMILARITY_LIMIT:
            found.append((a, b, len(words_a & words_b) / len(union)))
    return sorted(found, key=lambda item: -item[2])


def tight_clusters(lineages: list[Lineage]) -> list[list[str]]:
    related = {lineage.id: set(lineage.current().fm.get("related", [])) for lineage in lineages}
    topic = {lineage.id: lineage.current().fm["topic"] for lineage in lineages}
    edges: dict[str, set[str]] = {lid: set() for lid in related}
    for a, b in combinations(related, 2):
        if topic[a] == topic[b] and b in related[a] and a in related[b]:
            edges[a].add(b)
            edges[b].add(a)
    clusters, seen = [], set()
    for start in sorted(edges):
        if start in seen or not edges[start]:
            continue
        stack, group = [start], set()
        while stack:
            node = stack.pop()
            if node not in group:
                group.add(node)
                stack.extend(edges[node] - group)
        seen |= group
        if len(group) >= 3:
            clusters.append(sorted(group))
    return clusters


def aging_working(root: Path, lineages: list[Lineage], today: date) -> list[str]:
    found = []
    for lineage in lineages:
        for rev in lineage.revisions:
            changed = last_commit_date(root, rev.path)
            if rev.status == "working" and changed is not None and (today - changed).days > WORKING_STALE_DAYS:
                found.append(f"{lineage.id} revision {rev.label}: working, unchanged for {(today - changed).days} days")
    return found


def render(root: Path, report: bool, today: date) -> str:
    lineages = load_lineages(root)
    out = ["# Decision records worth a look", ""]
    detail = implementation_detail(lineages)
    out += ["## Reads like implementation detail (condense, or demote to a topic doc)"]
    out += [f"- {lid}: its Decision names {n} files" for lid, n in detail] or ["- none"]
    similar = similar_problems(lineages)
    out += ["", "## Similar problems (one problem stated for different cases? merge)"]
    out += [f"- {a} and {b}: {score:.0%} of their title, summary and Problem words in common" for a, b, score in similar] or ["- none"]
    clusters = tight_clusters(lineages)
    out += ["", "## Tight clusters (one decision split in pieces? merge)"]
    out += [f"- {', '.join(group)}" for group in clusters] or ["- none"]
    if report:
        out += ["", "# Quarterly report", "", "## Explorations that have stood still"]
        out += [f"- {w.removeprefix('warning: ')}" for w in stale_warnings(root, today)] or ["- none"]
        out += ["", "## Working revisions untouched for a long time"]
        out += [f"- {line}" for line in aging_working(root, lineages, today)] or ["- none"]
        out += ["", "## Active projects"]
        out += [f"- {w.removeprefix('warning: ')}" for w in active_project_warnings(root)] or ["- within the limit"]
        out += ["", 'Approved revisions that no project names are listed in the planning view\'s "Decisions awaiting a project".']
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true", help="also print the quarterly report")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)
    print(render(args.root, args.report, date.today()), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
