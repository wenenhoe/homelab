#!/usr/bin/env python3
"""Regenerates the two doc-index sections that were otherwise hand-edited
every time a project or draft doc is added or changes status:
docs/projects/README.md's Index table, and
docs/decisions/drafts/README.md's Open table (status, and which
project doc — if any — actually links to it).

Reads only YAML frontmatter, via doc_frontmatter.py (shared with
check-doc-drift.py) — schema documented in
docs/decisions/0028-doc-governance-frontmatter-and-nist-alignment.md.
Also validates every ADR/draft/project doc's type+status combination
along the way, even docs/decisions/*.md, which has no generated table
of its own — see that ADR for which status values are valid per type.
Deliberately doesn't touch docs/decisions/README.md's numbered-ADR
index itself: promotion into that index is a deliberate step
(renumbering, moving the file out of drafts/), not a side effect of
running this script — see docs/decisions/README.md's own promotion
section.

Run standalone, or via the pre-commit hook (wired in per ADR 0028).
Overwrites the two sections in place;
`git diff` shows whether anything actually changed.
"""

from __future__ import annotations

import re
import sys

from doc_frontmatter import ROOT, docs_in, read_frontmatter

# Project status -> display text for the regenerated table. "blocked"
# is built separately below since its display text embeds blocked_reason.
STATUS_DISPLAY = {
    "not-started": "Not started",
    "in-progress": "In progress",
    "done": "Done",
}


def project_status_text(fm: dict) -> str:
    if fm["status"] == "blocked":
        return f"Blocked: {fm['blocked_reason']}"
    return STATUS_DISPLAY[fm["status"]]


def render_projects_table() -> str:
    rows = []
    for path in docs_in(ROOT / "docs/projects"):
        fm = read_frontmatter(path)
        if "summary" not in fm:
            raise SystemExit(f"{path}: type: project docs need a 'summary' field for the Covers column")
        rows.append(f"| [`{path.name}`]({path.name}) | {project_status_text(fm)} | {fm['summary']} |")
    header = "| Project | Status | Covers |\n| :--- | :--- | :--- |"
    return "\n".join([header, *rows])


DRAFT_STATUS_DISPLAY = {
    "draft": "Draft",
    "de-risking": "De-risking",
    "decided": "Decided",
}


def find_linking_projects(draft_name: str) -> list:
    """Which project doc(s), if any, actually link to this draft — found
    by scanning docs/projects/*.md content for the filename, the same
    substring-matching check_doc_indexes() already uses elsewhere,
    rather than a second hand-maintained field that could drift from
    what's actually linked. A draft with no hit isn't necessarily
    incomplete: some are genuinely single-PR-scoped and never will have
    a project (see docs/projects/README.md's own bar for what needs
    one) - the empty case is rendered as "-", not an error.
    """
    return [path for path in docs_in(ROOT / "docs/projects") if draft_name in path.read_text(encoding="utf-8")]


def render_drafts_table() -> str:
    rows = []
    for path in docs_in(ROOT / "docs/decisions/drafts"):
        fm = read_frontmatter(path)
        status = DRAFT_STATUS_DISPLAY[fm["status"]]
        projects = find_linking_projects(path.name)
        project_cell = ", ".join(f"[`{p.name}`](../../projects/{p.name})" for p in projects) if projects else "—"
        rows.append(f"| [`{path.name}`]({path.name}) | {status} | {project_cell} |")
    header = "| Draft | Status | Project |\n| :--- | :--- | :--- |"
    return "\n".join([header, *rows])


def validate_adrs() -> None:
    """ADRs don't feed a generated table (see module docstring), but
    validating them here still catches a mismatched type/status before
    it ships — e.g. an ADR accidentally left at status: draft.
    """
    for path in docs_in(ROOT / "docs/decisions"):
        read_frontmatter(path)


def replace_section(text: str, heading: str, new_body: str) -> str:
    """Swaps the body of a top-level '## <heading>' section for new_body,
    leaving the heading line and everything outside the section alone.
    Matches through to the next '## ' heading or end of file.
    """
    pattern = re.compile(
        rf"(^## {re.escape(heading)}\n\n)(.*?)(\n\n(?=## )|\n*\Z)",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern.search(text)
    if not m:
        raise SystemExit(f"couldn't find a '## {heading}' section to regenerate")
    return text[: m.start(2)] + new_body + text[m.end(2) :]


def regenerate(path, heading: str, body: str) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(replace_section(text, heading, body), encoding="utf-8")


def main() -> int:
    validate_adrs()
    regenerate(ROOT / "docs/projects/README.md", "Index", render_projects_table())
    regenerate(ROOT / "docs/decisions/drafts/README.md", "Open", render_drafts_table())
    print("Regenerated docs/projects/README.md and docs/decisions/drafts/README.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
