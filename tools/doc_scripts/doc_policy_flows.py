"""The gateway's zone policy names its flows, and no doc cites one by its number.

A flow of the zone policy (`docs/topics/infra/tofu/opnsense-gateway.md`, "Zone
policy") is known by the name in the table's first column. A number is its place
in the table, so a cite by number points at the wrong flow once a row is added or
moved. Two rules, as pure functions returning error strings for check_doc_drift.py:

- the table's first column holds one name per row, written as a code span of
  lowercase words joined by hyphens, and no name is used twice;
- a link to the section whose text is such a name (`[`operator-gateway`](#zone-policy)`)
  names a flow that exists, and no doc that links the gateway doc cites "row 7" or
  "rows 7 and 12". The decisions are frozen and keep the numbers they were written with.
"""

from __future__ import annotations

import re
from pathlib import Path

from doc_scripts.doc_frontmatter import GENERATED_VIEWS, ROOT
from doc_scripts.doc_stage_words import split_units

POLICY_DOC = "docs/topics/infra/tofu/opnsense-gateway.md"
POLICY_HEADING = "## Zone policy"
SKIP_PREFIXES = ("docs/decisions/", "tools/tests/")

_NAME = r"[a-z0-9]+(?:-[a-z0-9]+)+"
FIRST_CELL_RE = re.compile(rf"`({_NAME})`")
# A link to the zone policy, from another doc or from within the gateway doc. The file name is optional so that
# `](#zone-policy)` counts only in the gateway doc, where it means the same section.
FLOW_LINK_RE = re.compile(rf"\[`({_NAME})`\]\((?:[^)\s]*opnsense-gateway\.md)?#zone-policy\)")
POLICY_LINK_RE = re.compile(r"\]\([^)\s]*opnsense-gateway\.md(?:#[^)]*)?\)")
ROW_NUMBER_RE = re.compile(r"\b[Rr]ows?\s+#?\d+")


def _table(text: str) -> list[tuple[int, str]] | None:
    """[(line, first cell)] of each row of the table in the zone policy section, or None when it has no table."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == POLICY_HEADING), None)
    if start is None:
        return None
    rows: list[tuple[int, str]] = []
    header = None
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            if header is not None:
                break
            continue
        cell = line.strip().strip("|").split("|")[0].strip()
        if header is None:
            header = i + 1
        elif not (cell and set(cell) <= set(":-")):
            rows.append((i + 1, cell))
    return None if header is None else rows


def flow_names(root: Path = ROOT) -> list[str]:
    """The names the zone policy's table gives its flows, in table order."""
    path = root / POLICY_DOC
    table = _table(path.read_text(encoding="utf-8")) if path.is_file() else None
    names = (FIRST_CELL_RE.fullmatch(cell) for _, cell in (table or []))
    return [m.group(1) for m in names if m]


def _table_errors(root: Path) -> list[str]:
    path = root / POLICY_DOC
    if not path.is_file():
        return []
    table = _table(path.read_text(encoding="utf-8"))
    if table is None:
        return [f"{POLICY_DOC}: has no table under '{POLICY_HEADING}' for the flows to be named in"]
    errors = []
    seen: dict[str, int] = {}
    for number, cell in table:
        match = FIRST_CELL_RE.fullmatch(cell)
        if not match:
            errors.append(
                f"{POLICY_DOC}:{number}: the first cell is {cell!r}, not a flow name. Write the name as a code span of "
                "lowercase words joined by hyphens, such as `operator-gateway`"
            )
        elif match.group(1) in seen:
            errors.append(f"{POLICY_DOC}:{number}: the flow name {match.group(1)} is already used by line {seen[match.group(1)]}")
        else:
            seen[match.group(1)] = number
    return errors


def _citation_errors(root: Path, names: set[str]) -> list[str]:
    errors = []
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root).as_posix()
        if not f.is_file() or ".git" in f.parts or "node_modules" in f.parts or rel.startswith(SKIP_PREFIXES) or rel in GENERATED_VIEWS:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        in_policy_doc = rel == POLICY_DOC
        if not (in_policy_doc or POLICY_LINK_RE.search(text)):
            continue
        for number, unit in split_units(text):
            if ROW_NUMBER_RE.search(unit):
                errors.append(
                    f"{rel}:{number}: cites a row of the zone policy by its number. Cite the flow by the name in the table's "
                    "first column, as [`operator-gateway`](#zone-policy) does, since a number changes when a row is added or moved"
                )
            for link in FLOW_LINK_RE.finditer(unit):
                bare = link.group(0).endswith("](#zone-policy)")
                if (bare and not in_policy_doc) or link.group(1) in names:
                    continue
                errors.append(f"{rel}:{number}: names the flow {link.group(1)}, which is not in the zone policy's table")
    return errors


def policy_flow_errors(root: Path = ROOT) -> list[str]:
    if not (root / POLICY_DOC).is_file():
        return []
    return _table_errors(root) + _citation_errors(root, set(flow_names(root)))
