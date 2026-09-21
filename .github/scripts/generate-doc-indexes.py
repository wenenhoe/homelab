#!/usr/bin/env python3
"""Regenerates the doc-index sections that would otherwise be hand-edited
every time a project, draft, or decision lineage is added or changes
status:

- docs/projects/README.md: `## Index` (always) and `## By initiative`
  (only if that heading exists).
- docs/decisions/drafts/README.md: `## Open` (status, and which project
  doc — if any — actually links to the draft).
- docs/decisions/README.md: `## Lineages`, grouped by topic (only if
  that heading exists).

Reads only YAML frontmatter, via doc_frontmatter.py (shared with
check-doc-drift.py), which is also the schema of record. Validating
every decision/draft/project doc's type and status along the way is a
side effect: a bad combination fails here before it ships.

Run standalone, or via the pre-commit hook. Overwrites the sections in
place; `git diff` shows whether anything actually changed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from doc_frontmatter import ROOT, TOPICS, Lineage, docs_in, load_lineages, read_frontmatter

# Project status -> display text for the regenerated table. The legacy
# `blocked` status is built separately below since its display text
# embeds blocked_reason.
STATUS_DISPLAY = {
    "not-started": "Not started",
    "de-risking": "De-risking",
    "building": "Building",
    "in-progress": "In progress",
    "done": "Done",
}


def project_status_text(fm: dict, waiting_on: list[str]) -> str:
    if fm["status"] == "blocked":
        return f"Blocked: {fm['blocked_reason']}"
    text = STATUS_DISPLAY[fm["status"]]
    if fm.get("blocked"):
        text += f" — blocked: {fm['blocked_reason']}"
    if waiting_on:
        text += " — waiting on " + ", ".join(waiting_on)
    return text


def _load_projects(root: Path) -> dict[str, tuple[Path, dict]]:
    projects = {}
    for path in docs_in(root / "docs/projects"):
        fm = read_frontmatter(path)
        projects[fm["id"]] = (path, fm)
    return projects


def _waiting_on(fm: dict, projects: dict[str, tuple[Path, dict]]) -> list[str]:
    """Predecessors that still exist as project docs. A finished project
    is deleted, so an existing one is by definition not finished.
    """
    return [f"[`{projects[d['project']][0].name}`]({projects[d['project']][0].name})" for d in fm.get("depends_on", []) if d["project"] in projects]


def render_projects_table(root: Path = ROOT) -> str:
    projects = _load_projects(root)
    rows = []
    for path, fm in projects.values():
        rows.append(f"| [`{path.name}`]({path.name}) | {project_status_text(fm, _waiting_on(fm, projects))} | {fm['summary']} |")
    header = "| Project | Status | Covers |\n| :--- | :--- | :--- |"
    return "\n".join([header, *rows])


def render_initiatives_table(root: Path = ROOT) -> str:
    projects = _load_projects(root)
    labelled = sorted((fm["super_project"], fm.get("track", ""), fm.get("phase", ""), path.name, fm) for path, fm in projects.values() if "super_project" in fm)
    if not labelled:
        return "No project is grouped into an initiative."
    counts: dict[str, int] = {}
    for initiative, *_ in labelled:
        counts[initiative] = counts.get(initiative, 0) + 1
    for initiative, n in counts.items():
        if n == 1:
            print(f"warning: super_project '{initiative}' is used by one project only — a typo, or not yet an initiative", file=sys.stderr)
    rows = [
        f"| `{initiative}` | {f'`{track}`' if track else '—'} | {f'`{phase}`' if phase else '—'} | [`{name}`]({name}) "
        f"| {project_status_text(fm, _waiting_on(fm, projects))} |"
        for initiative, track, phase, name, fm in labelled
    ]
    return "\n".join(["| Initiative | Track | Phase | Project | Status |\n| :--- | :--- | :--- | :--- | :--- |", *rows])


DRAFT_STATUS_DISPLAY = {
    "draft": "Draft",
    "de-risking": "De-risking",
    "decided": "Decided",
}


def find_linking_projects(draft_name: str, root: Path = ROOT) -> list:
    """Which project doc(s), if any, actually link to this draft — found
    by scanning docs/projects/*.md content for the filename, the same
    substring-matching check_doc_indexes() already uses elsewhere,
    rather than a second hand-maintained field that could drift from
    what's actually linked. A draft with no hit isn't necessarily
    incomplete: some are genuinely single-PR-scoped and never will have
    a project (see docs/projects/README.md's own bar for what needs
    one) - the empty case is rendered as "-", not an error.
    """
    return [path for path in docs_in(root / "docs/projects") if draft_name in path.read_text(encoding="utf-8")]


def render_drafts_table(root: Path = ROOT) -> str:
    rows = []
    for path in docs_in(root / "docs/decisions/drafts"):
        fm = read_frontmatter(path)
        status = DRAFT_STATUS_DISPLAY[fm["status"]]
        projects = find_linking_projects(path.name, root)
        project_cell = ", ".join(f"[`{p.name}`](../../projects/{p.name})" for p in projects) if projects else "—"
        rows.append(f"| [`{path.name}`]({path.name}) | {status} | {project_cell} |")
    header = "| Draft | Status | Project |\n| :--- | :--- | :--- |"
    return "\n".join([header, *rows])


ADR_STATUS_DISPLAY = {
    "working": "Working",
    "approved": "Approved",
    "accepted": "Accepted",
    "superseded": "Superseded",
    "abandoned": "Abandoned",
    "retired": "Retired",
}


def _revision_label(number: int) -> str:
    return "original" if number == 0 else f"revision {number}"


def _cell(text: str) -> str:
    return text.replace("|", r"\|")


def _lineage_link(lineage: Lineage) -> str:
    return f"[{lineage.number}]({lineage.dir.name}/{lineage.current().path.name})"


def render_lineages_index(root: Path = ROOT) -> str:
    lineages = load_lineages(root)
    if not lineages:
        return "No decision lineages yet."
    by_id = {lineage.id: lineage for lineage in lineages}
    narrowed_by: dict[str, set[str]] = {}
    related: dict[str, set[str]] = {}
    for lineage in lineages:
        for rev in lineage.revisions:
            if "narrows" in rev.fm:
                narrowed_by.setdefault(rev.fm["narrows"], set()).add(lineage.id)
            for other in rev.fm.get("related", []):
                related.setdefault(lineage.id, set()).add(other)
                related.setdefault(other, set()).add(lineage.id)

    sections = []
    for topic, topic_title in TOPICS.items():
        rows = []
        for lineage in lineages:
            current = lineage.current()
            if current.fm["topic"] != topic:
                continue
            status = ADR_STATUS_DISPLAY[current.status] + (f" ({_revision_label(current.number)})" if len(lineage.revisions) > 1 else "")
            notes = [f"Revision {r.number} {ADR_STATUS_DISPLAY[r.status].lower()}" for r in lineage.pending_successors()]
            if lineage.id in narrowed_by:
                notes.append("Narrowed by " + ", ".join(_lineage_link(by_id[i]) for i in sorted(narrowed_by[lineage.id])))
            if lineage.id in related:
                notes.append("Related: " + ", ".join(_lineage_link(by_id[i]) for i in sorted(related[lineage.id])))
            former = sorted({f for rev in lineage.revisions for f in rev.fm.get("former_ids", [])})
            if former:
                notes.append("Formerly " + ", ".join(former))
            cells = [
                _lineage_link(lineage),
                f"**{_cell(current.fm['title'])}** — {_cell(current.fm['summary'])}",
                _cell(current.fm["solution"]),
                status,
                _cell("; ".join(notes)) or "—",
            ]
            rows.append("| " + " | ".join(cells) + " |")
        if rows:
            header = "| ADR | Problem | Current solution | Status | Notes |\n| :--- | :--- | :--- | :--- | :--- |"
            sections.append("\n".join([f"### {topic_title}", "", header, *rows]))
    return "\n\n".join(sections)


def validate_adrs(root: Path = ROOT) -> None:
    """Lineage revisions are validated by load_lineages(). Reading any
    file sitting directly under docs/decisions/ fails: only lineage
    directories and drafts belong there.
    """
    for path in docs_in(root / "docs/decisions"):
        read_frontmatter(path)
    load_lineages(root)


def has_section(text: str, heading: str) -> bool:
    return re.search(rf"^## {re.escape(heading)}\n", text, re.MULTILINE) is not None


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


def regenerate(path: Path, heading: str, body: str, *, optional: bool = False) -> bool:
    text = path.read_text(encoding="utf-8")
    if optional and not has_section(text, heading):
        return False
    path.write_text(replace_section(text, heading, body), encoding="utf-8")
    return True


def main() -> int:
    validate_adrs()
    regenerate(ROOT / "docs/projects/README.md", "Index", render_projects_table())
    regenerate(ROOT / "docs/projects/README.md", "By initiative", render_initiatives_table(), optional=True)
    regenerate(ROOT / "docs/decisions/drafts/README.md", "Open", render_drafts_table())
    touched = ["docs/projects/README.md", "docs/decisions/drafts/README.md"]
    if regenerate(ROOT / "docs/decisions/README.md", "Lineages", render_lineages_index(), optional=True):
        touched.append("docs/decisions/README.md")
    print(f"Regenerated {', '.join(touched)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
