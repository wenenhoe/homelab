"""Removed decision numbers (ADR 0037 revision 4). Pure functions, shared by
check_accepted_records.py and check_doc_drift.py.

A lineage that held an accepted or superseded revision may leave the tree only
by being merged into another (that lineage lists its number in `former_ids`) or
demoted to a topic doc or dropped (its number is listed in `removed.md`). A
number is never reused, so a listed number can't be a live lineage and can't
be a former id.
"""

from __future__ import annotations

import re
from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT, load_lineages

LEDGER = "removed.md"
FATES = ("demoted", "dropped")
_ROW_RE = re.compile(r"^\| (\d{4}) \| (\w+) \| (.+) \|$")
_ANY_NUMBER_ROW_RE = re.compile(r"^\|\s*\d{4}\s*\|")
# Statuses that make a lineage worth keeping a record of when it leaves.
HELD_STATUSES = {"accepted", "superseded"}


def ledger_numbers(root: Path = ROOT) -> dict[str, tuple[str, str]]:
    """number -> (fate, where it went), read from the ledger's table rows."""
    path = root / "docs" / "decisions" / LEDGER
    if not path.is_file():
        return {}
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW_RE.match(line)
        if m and m.group(2) in FATES:
            rows[m.group(1)] = (m.group(2), m.group(3))
    return rows


def ledger_errors(root: Path = ROOT) -> list[str]:
    path = root / "docs" / "decisions" / LEDGER
    if not path.is_file():
        return []
    rel = path.relative_to(root)
    errors = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not _ANY_NUMBER_ROW_RE.match(line):
            continue
        m = _ROW_RE.match(line)
        if not m or m.group(2) not in FATES:
            errors.append(f"{rel}: the row '{line}' must read '| NNNN | {' or '.join(FATES)} | where it went |'")
            continue
        number = m.group(1)
        if number in seen:
            errors.append(f"{rel}: ADR {number} is listed twice")
        seen.add(number)
    lineages = load_lineages(root)
    live = {lineage.number for lineage in lineages}
    former = {f[4:] for lineage in lineages for rev in lineage.revisions for f in rev.fm.get("former_ids", [])}
    for number in sorted(seen):
        if number in live:
            errors.append(f"{rel}: ADR {number} is listed as removed, but the lineage exists — a number is never reused")
        if number in former:
            errors.append(f"{rel}: ADR {number} is listed as removed and is also a former id of a lineage; it went to one place")
    return errors


def removal_errors(base_lineages: dict[str, set[str]], result_root: Path = ROOT) -> list[str]:
    """`base_lineages` maps each lineage number on the base to the statuses its revisions had.
    Judged on what the change leaves: a lineage that held a held status and is gone must be
    accounted for."""
    lineages = load_lineages(result_root)
    live = {lineage.number for lineage in lineages}
    former = {f[4:] for lineage in lineages for rev in lineage.revisions for f in rev.fm.get("former_ids", [])}
    listed = ledger_numbers(result_root)
    errors = []
    for number, statuses in sorted(base_lineages.items()):
        if number in live or not (statuses & HELD_STATUSES) or number in former or number in listed:
            continue
        errors.append(
            f"ADR {number}: removed, but it held an accepted or superseded revision and is neither a former id of the lineage it was merged into "
            f"nor listed in docs/decisions/{LEDGER} — say where its reasoning went"
        )
    return errors
