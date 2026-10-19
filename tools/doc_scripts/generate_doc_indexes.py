#!/usr/bin/env python3
"""Regenerates the doc-index sections that would otherwise be hand-edited
every time a project or decision lineage is added or changes status:

- docs/projects/README.md: `## Index` (always).
- docs/project-planning.md: `## Next up`, `## Super Projects`, `## Projects`,
  and `## Decisions awaiting a project` (always).
- docs/decisions/README.md: `## Lineages`, grouped by topic (only if
  that heading exists).

Reads only YAML frontmatter, via doc_frontmatter.py (shared with
check_doc_drift.py), which is also the schema of record. Validating
every decision and project doc's type and status along the way is a
side effect: a bad combination fails here before it ships.

Run standalone, or via the pre-commit hook. Overwrites the sections in
place; `git diff` shows whether anything actually changed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT, TOPICS, Lineage, docs_in, load_lineages, read_frontmatter
from doc_scripts.doc_graph import duplicate_lineage_errors

# Project status -> display text for the regenerated table.
STATUS_DISPLAY = {
    "not-started": "Not started",
    "de-risking": "De-risking",
    "building": "Building",
    "done": "Done",
}


def project_status_text(fm: dict, waiting_on: list[str], decision_status: str | None = None, decision_link: str | None = None) -> str:
    """The status cell. `decision_status` is the state of the revision the
    project's `decision:` names, or None when it has none or it doesn't
    resolve (check_doc_drift.py reports the latter). `decision_link` is that
    revision as a markdown link, or None when it doesn't resolve, in which
    case the bare reference is shown."""
    text = STATUS_DISPLAY[fm["status"]]
    if fm.get("blocked"):
        text += f" — blocked: {fm['blocked_reason']}"
    if waiting_on:
        text += " — waiting on " + ", ".join(waiting_on)
    elif _is_ready(fm, decision_status):
        text += " — ready"
    elif _awaits_decision(fm, decision_status):
        text += f" — waiting on {decision_link or fm['decision']}"
    return text


def _awaits_decision(fm: dict, decision_status: str | None) -> bool:
    """A not-started project that is not blocked and whose decision revision is
    not approved: the state `_is_ready` rejects that neither a blocker nor a
    predecessor explains. Derived like `_is_ready`, so approving the revision
    changes the label with no edit to the project."""
    return fm["status"] == "not-started" and not fm.get("blocked") and "decision" in fm and decision_status != "approved"


def _is_ready(fm: dict, decision_status: str | None) -> bool:
    """A not-started project whose decision is approved (or that has none, so
    nothing gates it), that is not blocked, and whose predecessors are all gone.
    Derived like "waiting on", never stored: a revision that drops back to
    `working` stops the label with no edit to the project."""
    if fm["status"] != "not-started" or fm.get("blocked"):
        return False
    return decision_status == "approved" if "decision" in fm else True


def _decision_statuses(root: Path) -> dict[str, str]:
    """`ADR-NNNN/label` -> status, the same reference a project's `decision:` uses."""
    return {f"{lineage.id}/{rev.label}": rev.status for lineage in load_lineages(root) for rev in lineage.revisions}


def _decision_paths(root: Path) -> dict[str, str]:
    """`ADR-NNNN/label` -> the revision's path under docs/decisions/."""
    return {f"{lineage.id}/{rev.label}": f"{lineage.dir.name}/{rev.path.name}" for lineage in load_lineages(root) for rev in lineage.revisions}


def _load_projects(root: Path) -> dict[str, tuple[Path, dict]]:
    projects = {}
    for path in docs_in(root / "docs/projects"):
        fm = read_frontmatter(path)
        projects[fm["id"]] = (path, fm)
    return projects


def _waiting_on(fm: dict, projects: dict[str, tuple[Path, dict]], prefix: str = "") -> list[str]:
    """Predecessors that still exist as project docs. A finished project
    is deleted, so an existing one is by definition not finished. prefix
    is a path prefix for a caller rendering into a file outside
    docs/projects/ (docs/project-planning.md, not docs/projects/README.md).
    """
    return [f"[`{projects[d['project']][0].name}`]({prefix}{projects[d['project']][0].name})" for d in fm.get("depends_on", []) if d["project"] in projects]


def _status_cell(
    fm: dict,
    projects: dict[str, tuple[Path, dict]],
    decisions: dict[str, str],
    decision_paths: dict[str, str],
    *,
    project_prefix: str,
    decision_prefix: str,
) -> str:
    """The status cell for a view. The prefixes are the paths from the file the
    view renders into to docs/projects/ and to docs/decisions/."""
    ref = fm.get("decision")
    link = f"[{ref}]({decision_prefix}{decision_paths[ref]})" if ref in decision_paths else None
    return project_status_text(fm, _waiting_on(fm, projects, project_prefix), decisions.get(ref), link)


def _unblocks(projects: dict[str, tuple[Path, dict]]) -> dict[str, int]:
    """How many existing projects wait on each one, directly or through a chain of
    `depends_on`. Read from the same entries as `_waiting_on`, so a finished
    project's deleted doc drops out with no edit. A cycle is check_doc_drift.py's to
    report; here each project is counted once and never as its own dependent."""
    successors: dict[str, list[str]] = {pid: [] for pid in projects}
    for pid, (_, fm) in projects.items():
        for dep in fm.get("depends_on", []):
            if dep["project"] in successors:
                successors[dep["project"]].append(pid)

    def downstream(start: str) -> set[str]:
        seen: set[str] = set()
        pending = [start]
        while pending:
            for nxt in successors[pending.pop()]:
                if nxt != start and nxt not in seen:
                    seen.add(nxt)
                    pending.append(nxt)
        return seen

    return {pid: len(downstream(pid)) for pid in projects}


def _unblocks_cell(count: int) -> str:
    return str(count) if count else "—"


def render_projects_table(root: Path = ROOT) -> str:
    projects = _load_projects(root)
    decisions = _decision_statuses(root)
    decision_paths = _decision_paths(root)
    unblocks = _unblocks(projects)
    rows = []
    for pid, (path, fm) in projects.items():
        status = _status_cell(fm, projects, decisions, decision_paths, project_prefix="", decision_prefix="../decisions/")
        rows.append(f"| [`{path.name}`]({path.name}) | {_unblocks_cell(unblocks[pid])} | {status} | {fm['summary']} |")
    header = "| Project | Unblocks | Status | Covers |\n| :--- | ---: | :--- | :--- |"
    return "\n".join([header, *rows])


def render_standalone_projects_table(root: Path = ROOT) -> str:
    """Projects with no `super_project`: the complement of the Super
    Projects view below. Same three columns as projects/README.md's own
    Index (this function's rows are a filtered copy of that table, not
    a different shape), rendered with the `projects/` prefix since this
    lives one level above docs/projects/.
    """
    projects = _load_projects(root)
    decisions = _decision_statuses(root)
    decision_paths = _decision_paths(root)
    unblocks = _unblocks(projects)
    rows = [
        f"| [`{path.name}`](projects/{path.name}) | {_unblocks_cell(unblocks[pid])} "
        f"| {_status_cell(fm, projects, decisions, decision_paths, project_prefix='projects/', decision_prefix='decisions/')} | {fm['summary']} |"
        for pid, (path, fm) in projects.items()
        if "super_project" not in fm
    ]
    if not rows:
        return "Every project belongs to a super-project."
    header = "| Project | Unblocks | Status | Covers |\n| :--- | ---: | :--- | :--- |"
    return "\n".join([header, *rows])


# Building comes first so started work finishes before new work opens, then spikes, then ready work.
NEXT_UP_RANK = {"building": 0, "de-risking": 1, "not-started": 2}


def render_next_up_table(root: Path = ROOT) -> str:
    """Projects that can be worked on now: not done, not blocked, waiting on no
    existing project, and, when not started, ready. Ordered by lifecycle status,
    then by how many projects wait on it, then by name. Renders into
    docs/project-planning.md, so links carry the `projects/` prefix."""
    projects = _load_projects(root)
    decisions = _decision_statuses(root)
    unblocks = _unblocks(projects)
    startable = []
    for pid, (path, fm) in projects.items():
        decision_status = decisions.get(fm.get("decision"))
        if fm["status"] == "done" or fm.get("blocked") or _waiting_on(fm, projects):
            continue
        if fm["status"] == "not-started" and not _is_ready(fm, decision_status):
            continue
        key = (NEXT_UP_RANK[fm["status"]], -unblocks[pid], path.name)
        startable.append((key, path.name, fm, decision_status, unblocks[pid]))
    if not startable:
        return "No project is ready to work on."
    rows = [
        f"| [`{name}`](projects/{name}) | {_unblocks_cell(count)} | {project_status_text(fm, [], decision_status)} | {fm['summary']} |"
        for _, name, fm, decision_status, count in sorted(startable, key=lambda e: e[0])
    ]
    header = "| Project | Unblocks | Status | Covers |\n| :--- | ---: | :--- | :--- |"
    return "\n".join([header, *rows])


def _dependency_depths(projects: dict[str, tuple[Path, dict]]) -> dict[str, int]:
    """How far down its dependency chain each project sits: 0 with no existing
    predecessor, else one more than its deepest. Reading order for the initiative
    view. A cycle is check_doc_drift.py's to report; here it only stops recursing."""
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def depth(pid: str) -> int:
        if pid in memo:
            return memo[pid]
        if pid in visiting:
            return 0
        visiting.add(pid)
        predecessors = [d["project"] for d in projects[pid][1].get("depends_on", []) if d["project"] in projects]
        memo[pid] = 1 + max(depth(p) for p in predecessors) if predecessors else 0
        visiting.discard(pid)
        return memo[pid]

    return {pid: depth(pid) for pid in projects}


def render_initiatives_table(root: Path = ROOT) -> str:
    """Rows are grouped by initiative, then by track in build order (a track sorts by
    its earliest project in the dependency chain, then by name), then by phase slug,
    then by dependency depth, then by filename."""
    projects = _load_projects(root)
    decisions = _decision_statuses(root)
    decision_paths = _decision_paths(root)
    depths = _dependency_depths(projects)
    unblocks = _unblocks(projects)
    entries = [
        (fm["super_project"], fm.get("track", ""), fm.get("phase", ""), depths[pid], path.name, fm)
        for pid, (path, fm) in projects.items()
        if "super_project" in fm
    ]
    earliest: dict[tuple[str, str], int] = {}
    for initiative, track, _, depth, _, _ in entries:
        earliest[(initiative, track)] = min(earliest.get((initiative, track), depth), depth)
    labelled = sorted(entries, key=lambda e: (e[0], earliest[(e[0], e[1])], e[1], e[2], e[3], e[4]))
    if not labelled:
        return "No project is grouped into an initiative."
    counts: dict[str, int] = {}
    for initiative, *_ in labelled:
        counts[initiative] = counts.get(initiative, 0) + 1
    for initiative, n in counts.items():
        if n == 1:
            print(f"warning: super_project '{initiative}' is used by one project only — a typo, or not yet an initiative", file=sys.stderr)
    # Renders into docs/project-planning.md, one level above docs/projects/ — every link needs that prefix.
    # Initiative repeats down a run of rows since the sort above already
    # groups them contiguously; blank it on every row after the first of
    # a run so the table reads as one block per initiative instead of
    # repeating the label. Track is left printed every row — see the
    # Track/Phase columns' own grouping instead. A blank cell renders as
    # a single space between its pipes ("| |"), not the two spaces a
    # populated cell's padding would otherwise leave — MD060's compact
    # table style (.config/.markdownlint.yaml) flags the latter.
    rows = []
    prev_initiative: str | None = None
    for initiative, track, phase, _, name, fm in labelled:
        initiative_cell = f" `{initiative}` " if initiative != prev_initiative else " "
        prev_initiative = initiative
        rows.append(
            f"|{initiative_cell}| {f'`{track}`' if track else '—'} | {f'`{phase}`' if phase else '—'} | [`{name}`](projects/{name}) "
            f"| {_unblocks_cell(unblocks[fm['id']])} "
            f"| {_status_cell(fm, projects, decisions, decision_paths, project_prefix='projects/', decision_prefix='decisions/')} |"
        )
    header = "| Initiative | Track | Phase | Project | Unblocks | Status |\n| :--- | :--- | :--- | :--- | ---: | :--- |"
    return "\n".join([header, *rows])


ADR_STATUS_DISPLAY = {
    "working": "Working",
    "approved": "Approved",
    "accepted": "Accepted",
    "superseded": "Superseded",
    "abandoned": "Abandoned",
    "retired": "Retired",
}


def _revision_label(rev) -> str:
    base = "original" if rev.number == 0 else f"revision {rev.number}"
    return f"{base} ({rev.candidate})" if rev.candidate else base


def _short_label(rev) -> str:
    return f"{rev.number:03d}" + (f"-{rev.candidate}" if rev.candidate else "")


def _cell(text: str) -> str:
    return text.replace("|", r"\|")


def _lineage_link(lineage: Lineage, prefix: str = "") -> str:
    return f"[{lineage.number}]({prefix}{lineage.dir.name}/{lineage.current().path.name})"


def _adr_solution_cells(lineage: Lineage, prefix: str = "") -> tuple[str, str, str]:
    """(adr_cell, solution, status) for one lineage's row, shared by every
    generated ADR table. Several open candidates with nothing accepted yet
    say so explicitly, rather than showing the alphabetically-last one as
    if it had won (Lineage.current() would otherwise pick it by construction).
    prefix is a path prefix for a caller rendering outside docs/decisions/
    (docs/project-planning.md, not docs/decisions/README.md).
    """
    current = lineage.current()
    open_revisions = [r for r in lineage.revisions if r.status in ("working", "approved")]
    decided = any(r.status in ("accepted", "retired") for r in lineage.revisions)
    if not decided and len(open_revisions) > 1:
        first = open_revisions[0]
        solution = "Undecided between: " + "; or ".join(f"({_short_label(r)}) {r.fm['solution']}" for r in open_revisions)
        status = ", ".join(f"{ADR_STATUS_DISPLAY[r.status]} ({_short_label(r)})" for r in open_revisions)
        adr_cell = f"[{lineage.number}]({prefix}{lineage.dir.name}/{first.path.name})"
    else:
        solution = current.fm["solution"]
        status = ADR_STATUS_DISPLAY[current.status] + (f" ({_revision_label(current)})" if len(lineage.revisions) > 1 else "")
        adr_cell = _lineage_link(lineage, prefix)
    return adr_cell, solution, status


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
            adr_cell, solution, status = _adr_solution_cells(lineage)
            open_revisions = [r for r in lineage.revisions if r.status in ("working", "approved")]
            decided = any(r.status in ("accepted", "retired") for r in lineage.revisions)
            notes = (
                []
                if not decided and len(open_revisions) > 1
                else [f"Revision {r.label} {ADR_STATUS_DISPLAY[r.status].lower()}" for r in lineage.pending_successors()]
            )
            if lineage.id in narrowed_by:
                notes.append("Narrowed by " + ", ".join(_lineage_link(by_id[i]) for i in sorted(narrowed_by[lineage.id])))
            if lineage.id in related:
                notes.append("Related: " + ", ".join(_lineage_link(by_id[i]) for i in sorted(related[lineage.id])))
            former = sorted({f for rev in lineage.revisions for f in rev.fm.get("former_ids", [])})
            if former:
                notes.append("Formerly " + ", ".join(former))
            cells = [adr_cell, f"**{_cell(current.fm['title'])}** — {_cell(current.fm['summary'])}", _cell(solution), status, _cell("; ".join(notes)) or "—"]
            rows.append("| " + " | ".join(cells) + " |")
        if rows:
            header = "| ADR | Problem | Current solution | Status | Notes |\n| :--- | :--- | :--- | :--- | :--- |"
            sections.append("\n".join([f"### {topic_title}", "", header, *rows]))
    return "\n\n".join(sections)


def _approved_first(uncovered) -> int:
    """Sort key for the awaiting-a-project table: an approved revision that no
    project names is the one gap there that calls for a project, so it sorts
    ahead of a working one."""
    return 0 if any(r.status == "approved" for r in uncovered) else 1


def render_needs_project_table(root: Path = ROOT) -> str:
    """Every ADR lineage with at least one open (working/approved)
    revision that appears in no project's decision: or also_implements:.
    Includes a pending successor to an already-accepted revision (shown
    as the successor's own proposal, not the shipped parent's), since
    that successor is itself uncovered even though the lineage overall
    looks 'done' by its current() answer. Rows with an approved
    uncovered revision come first, each group in lineage order. Doesn't
    know about a project that only mentions the lineage in free prose
    with neither field set — see ADR 0037 revision 1's Consequences.
    """
    lineages = load_lineages(root)
    covered: set[str] = set()
    for path in docs_in(root / "docs/projects"):
        fm = read_frontmatter(path)
        if "decision" in fm:
            covered.add(fm["decision"])
        covered.update(fm.get("also_implements", []))

    entries: list[tuple[int, str]] = []
    for lineage in lineages:
        open_revisions = [r for r in lineage.revisions if r.status in ("working", "approved")]
        uncovered = [r for r in open_revisions if f"{lineage.id}/{r.label}" not in covered]
        if not uncovered:
            continue
        current = lineage.current()
        problem = f"**{_cell(current.fm['title'])}** — {_cell(current.fm['summary'])}"
        if current.status in ("accepted", "retired"):
            # current() is the shipped answer; what's actually uncovered is a
            # pending successor proposing to replace it — show that, not the
            # already-implemented parent.
            for r in uncovered:
                adr_cell = f"[{lineage.number}](decisions/{lineage.dir.name}/{r.path.name})"
                solution = f"Proposed revision {r.label}: {r.fm['solution']}"
                status = f"{ADR_STATUS_DISPLAY[r.status]} (proposed revision {r.label})"
                entries.append((_approved_first([r]), "| " + " | ".join([adr_cell, problem, _cell(solution), status]) + " |"))
        else:
            adr_cell, solution, status = _adr_solution_cells(lineage, prefix="decisions/")
            entries.append((_approved_first(uncovered), "| " + " | ".join([adr_cell, problem, _cell(solution), status]) + " |"))
    if not entries:
        return "Every open ADR is named in some project's `decision:` or `also_implements:`."
    # sorted() is stable, so each group keeps the lineage order the loop produced.
    rows = [row for _, row in sorted(entries, key=lambda e: e[0])]
    header = "| ADR | Problem | Current solution | Status |\n| :--- | :--- | :--- | :--- |"
    return "\n".join([header, *rows])


def validate_adrs(root: Path = ROOT) -> None:
    """Lineage revisions are validated by load_lineages(). Reading any
    file sitting directly under docs/decisions/ fails: only lineage
    directories belong there. So do two lineage directories that share a
    number, which would otherwise be indexed side by side.
    """
    for path in docs_in(root / "docs/decisions"):
        read_frontmatter(path)
    errors = duplicate_lineage_errors(load_lineages(root), root)
    if errors:
        raise SystemExit("\n".join([*errors, "Renumber the lineage a patch series adds with `python3 -m doc_scripts.renumber_adr_patches`."]))


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
    touched = ["docs/projects/README.md"]
    regenerate(ROOT / "docs/project-planning.md", "Next up", render_next_up_table())
    regenerate(ROOT / "docs/project-planning.md", "Super Projects", render_initiatives_table())
    regenerate(ROOT / "docs/project-planning.md", "Projects", render_standalone_projects_table())
    regenerate(ROOT / "docs/project-planning.md", "Decisions awaiting a project", render_needs_project_table())
    touched.append("docs/project-planning.md")
    if regenerate(ROOT / "docs/decisions/README.md", "Lineages", render_lineages_index(), optional=True):
        touched.append("docs/decisions/README.md")
    print(f"Regenerated {', '.join(touched)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
