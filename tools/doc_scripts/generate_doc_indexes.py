#!/usr/bin/env python3
"""Regenerates the doc-index sections that would otherwise be hand-edited
every time a project or decision lineage is added or changes status:

- docs/project-planning.md: `## Roadmap`, `## Super Projects`, `## Projects`,
  `## Decisions awaiting a project`, and `## Open explorations` (always).
- docs/decision-index.md: `## By number`, `## By topic`, `## Open decisions`
  and `## History` (always).
- docs/topics/disaster-recovery/coverage.md: `## Apps` (always), the
  per-app coverage table.

Reads only YAML frontmatter, via doc_frontmatter.py (shared with
check_doc_drift.py), which is also the schema of record. Validating
every decision and project doc's type and status along the way is a
side effect: a bad combination fails here before it ships.

Run standalone, or via the pre-commit hook. Overwrites the sections in
place; `git diff` shows whether anything actually changed.
"""

from __future__ import annotations

import functools
import re
import sys
from pathlib import Path

from doc_scripts.doc_coverage import COVERAGE_RELATIVE, render_coverage_table
from doc_scripts.doc_explorations import last_commit_date, load_explorations
from doc_scripts.doc_frontmatter import DECISION_INDEX, ROOT, TOPICS, Lineage, docs_in, load_lineages, read_frontmatter
from doc_scripts.doc_graph import duplicate_lineage_errors
from doc_scripts.doc_reliance import unmet_reliances
from doc_scripts.doc_removed import LEDGER

# Project status -> display text for the regenerated table.
STATUS_DISPLAY = {
    "not-started": "Not started",
    "de-risking": "De-risking",
    "building": "Building",
    "done": "Done",
}


def project_status_cells(
    fm: dict,
    waiting_on: list[str],
    decision_status: str | None = None,
    decision_link: str | None = None,
    rests_on: list[str] | None = None,
) -> tuple[str, str]:
    """The Status and Blocker cells. `decision_status` is the state of the revision the
    project's `decision:` names, or None when it has none or it doesn't
    resolve (check_doc_drift.py reports the latter). `decision_link` is that
    revision as a markdown link, or None when it doesn't resolve, in which
    case the bare reference is shown. `rests_on` are the targets of the decision revision's
    unmet reliances, each as `ADR-NNNN (state)`. The Blocker cell is `—` when nothing is in the
    way, which for a not-started project means it is ready."""
    blockers = []
    if fm.get("blocked"):
        blockers.append(f"blocked: {fm['blocked_reason']}")
    if waiting_on:
        blockers.append("waiting on " + ", ".join(waiting_on))
    elif _awaits_decision(fm, decision_status):
        blockers.append(f"waiting on {decision_link or fm['decision']}")
    if rests_on:
        blockers.append("rests on " + ", ".join(rests_on))
    return STATUS_DISPLAY[fm["status"]], "; ".join(blockers) or "—"


def _awaits_decision(fm: dict, decision_status: str | None) -> bool:
    """A not-started project that is not blocked and whose decision revision is
    not approved: a project that neither a blocker nor a predecessor explains
    is waiting on. Derived, never stored, so approving the revision changes the
    label with no edit to the project."""
    return fm["status"] == "not-started" and not fm.get("blocked") and "decision" in fm and decision_status != "approved"


def _decision_statuses(root: Path) -> dict[str, str]:
    """`ADR-NNNN/label` -> status, the same reference a project's `decision:` uses."""
    return {f"{lineage.id}/{rev.label}": rev.status for lineage in load_lineages(root) for rev in lineage.revisions}


def _decision_shorts(root: Path) -> dict[str, str]:
    """`ADR-NNNN/label` -> the revision's short name."""
    return {f"{lineage.id}/{rev.label}": rev.fm["short"] for lineage in load_lineages(root) for rev in lineage.revisions}


def _decision_paths(root: Path) -> dict[str, str]:
    """`ADR-NNNN/label` -> the revision's path under docs/decisions/."""
    return {f"{lineage.id}/{rev.label}": f"{lineage.dir.name}/{rev.path.name}" for lineage in load_lineages(root) for rev in lineage.revisions}


def _rests_on(root: Path) -> dict[str, list[str]]:
    """`ADR-NNNN/label` -> the unmet reliances of that revision, as `ADR-NNNN (working)`. Derived
    on each run and never stored, so settling the target changes the label with no edit."""
    rests_on: dict[str, list[str]] = {}
    for unmet in unmet_reliances(root):
        ref = f"{unmet.reliant.fm['id']}/{unmet.reliant.label}"
        rests_on.setdefault(ref, []).append(f"{unmet.target} ({unmet.target_state})")
    return rests_on


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


def _status_pair(
    fm: dict,
    projects: dict[str, tuple[Path, dict]],
    decisions: dict[str, str],
    decision_paths: dict[str, str],
    decision_shorts: dict[str, str],
    *,
    project_prefix: str,
    decision_prefix: str,
    rests_on: dict[str, list[str]] | None = None,
) -> tuple[str, str]:
    """The Status and Blocker cells for a view. The prefixes are the paths from the file the
    view renders into to docs/projects/ and to docs/decisions/."""
    ref = fm.get("decision")
    text = f"{ref} ({decision_shorts[ref]})" if ref in decision_shorts else ref
    link = f"[{text}]({decision_prefix}{decision_paths[ref]})" if ref in decision_paths else None
    return project_status_cells(fm, _waiting_on(fm, projects, project_prefix), decisions.get(ref), link, (rests_on or {}).get(ref))


def _status_cells(*args, **kwargs) -> str:
    """The Status and Blocker cells of `_status_pair`, as the two cells of a row."""
    return " | ".join(_status_pair(*args, **kwargs))


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


# Building comes first so started work finishes before new work opens, then spikes, then work not started.
STATUS_ORDER = {"building": 0, "de-risking": 1, "not-started": 2, "done": 3}


def _by_status(projects: dict[str, tuple[Path, dict]]) -> list[tuple[str, tuple[Path, dict]]]:
    """The projects ordered by lifecycle status, then by file name."""
    return sorted(projects.items(), key=lambda item: (STATUS_ORDER[item[1][1]["status"]], item[1][0].name))


def _unblocks_cell(count: int) -> str:
    return str(count) if count else "—"


def render_standalone_projects_table(root: Path = ROOT) -> str:
    """Projects with no `super_project`: the complement of the Super
    Projects view below, with the same columns plus Covers, rendered with the
    `projects/` prefix since this lives one level above docs/projects/.
    """
    projects = _load_projects(root)
    decisions = _decision_statuses(root)
    decision_paths = _decision_paths(root)
    decision_shorts = _decision_shorts(root)
    unblocks = _unblocks(projects)
    rests_on = _rests_on(root)
    cells = functools.partial(
        _status_cells,
        projects=projects,
        decisions=decisions,
        decision_paths=decision_paths,
        decision_shorts=decision_shorts,
        project_prefix="projects/",
        decision_prefix="decisions/",
        rests_on=rests_on,
    )
    rows = [
        f"| [`{path.name}`](projects/{path.name}) | {_unblocks_cell(unblocks[pid])} | {cells(fm)} | {_cell(fm['summary'])} |"
        for pid, (path, fm) in _by_status(projects)
        if "super_project" not in fm
    ]
    if not rows:
        return "Every project belongs to a super-project."
    header = "| Project | Unblocks | Status | Blocker | Covers |\n| :--- | ---: | :--- | :--- | :--- |"
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
    """Rows are grouped by initiative, then ordered by dependency depth, then by filename."""
    projects = _load_projects(root)
    decisions = _decision_statuses(root)
    decision_paths = _decision_paths(root)
    decision_shorts = _decision_shorts(root)
    depths = _dependency_depths(projects)
    unblocks = _unblocks(projects)
    rests_on = _rests_on(root)
    entries = [(fm["super_project"], depths[pid], path.name, fm) for pid, (path, fm) in projects.items() if "super_project" in fm]
    labelled = sorted(entries, key=lambda e: (e[0], e[1], e[2]))
    if not labelled:
        return "No project is grouped into an initiative."
    counts: dict[str, int] = {}
    for initiative, *_ in labelled:
        counts[initiative] = counts.get(initiative, 0) + 1
    for initiative, n in counts.items():
        if n == 1:
            print(f"warning: super_project '{initiative}' is used by one project only — a typo, or not yet an initiative", file=sys.stderr)
    # Renders into docs/project-planning.md, one level above docs/projects/ — every link needs that prefix.
    # The sort above already groups an initiative's rows; blank its label on every row after the
    # first of a run so the table reads as one block per initiative. A blank cell renders as a
    # single space between its pipes ("| |"), not the two spaces a populated cell's padding
    # would otherwise leave — MD060's compact table style (.config/.markdownlint.yaml) flags the latter.
    rows = []
    prev_initiative: str | None = None
    for initiative, _, name, fm in labelled:
        initiative_cell = f" `{initiative}` " if initiative != prev_initiative else " "
        prev_initiative = initiative
        cells = _status_cells(
            fm, projects, decisions, decision_paths, decision_shorts, project_prefix="projects/", decision_prefix="decisions/", rests_on=rests_on
        )
        rows.append(f"|{initiative_cell}| [`{name}`](projects/{name}) | {_unblocks_cell(unblocks[fm['id']])} | {cells} | {_cell(fm['summary'])} |")
    header = "| Initiative | Project | Unblocks | Status | Blocker | Covers |\n| :--- | :--- | ---: | :--- | :--- | :--- |"
    return "\n".join([header, *rows])


INITIATIVES_HEADING = "Initiatives"
INITIATIVES_RELATIVE = "docs/projects/README.md"
_INITIATIVE_ITEM = re.compile(r"^\d+\. `([^`]+)`", re.MULTILINE)


def load_initiative_order(root: Path = ROOT) -> list[str]:
    """The initiatives in the order the maintainer keeps them: the numbered list under
    `## Initiatives` in docs/projects/README.md. The only stored order, and it holds initiatives,
    never projects."""
    text = (root / INITIATIVES_RELATIVE).read_text(encoding="utf-8") if (root / INITIATIVES_RELATIVE).is_file() else ""
    section = re.search(rf"^## {INITIATIVES_HEADING}\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    if not section:
        raise SystemExit(f"{INITIATIVES_RELATIVE} has no '## {INITIATIVES_HEADING}' section, so the roadmap has no order to follow")
    return _INITIATIVE_ITEM.findall(section.group(1))


def initiative_list_errors(order: list[str], used: set[str]) -> list[str]:
    """What keeps the list complete: every `super_project` is listed, once, and every listed
    initiative has a project."""
    errors = [f"initiative '{name}' is listed more than once in {INITIATIVES_RELATIVE}" for name in dict.fromkeys(n for n in order if order.count(n) > 1)]
    errors += [f"super_project '{name}' is not in the initiative list in {INITIATIVES_RELATIVE}" for name in sorted(used - set(order))]
    errors += [f"initiative '{name}' in {INITIATIVES_RELATIVE} has no project" for name in order if name not in used]
    return errors


ROADMAP_COLUMNS = ("In progress", "Startable", "Waiting")
NO_INITIATIVE = "(no initiative)"


def render_roadmap_table(root: Path = ROOT) -> str:
    """One row per initiative in the kept order, then a row for projects with no `super_project`.
    A project's column comes from its status and Blocker cell; a `done` project is not shown.
    Fails, naming each, when the initiative list and the projects' `super_project` values disagree."""
    projects = _load_projects(root)
    order = load_initiative_order(root)
    errors = initiative_list_errors(order, {fm["super_project"] for _, fm in projects.values() if "super_project" in fm})
    if errors:
        raise SystemExit("\n".join(errors))
    decisions = _decision_statuses(root)
    decision_paths = _decision_paths(root)
    decision_shorts = _decision_shorts(root)
    depths = _dependency_depths(projects)
    unblocks = _unblocks(projects)
    rests_on = _rests_on(root)
    columns: dict[str | None, dict[str, list[tuple[int, str, str]]]] = {}
    for pid, (path, fm) in projects.items():
        if fm["status"] == "done":
            continue
        _, blocker = _status_pair(
            fm, projects, decisions, decision_paths, decision_shorts, project_prefix="projects/", decision_prefix="decisions/", rests_on=rests_on
        )
        started = fm["status"] in ("building", "de-risking")
        column = "In progress" if started else ("Startable" if blocker == "—" else "Waiting")
        count = f" (unblocks {unblocks[pid]})" if unblocks[pid] else ""
        columns.setdefault(fm.get("super_project"), {}).setdefault(column, []).append((depths[pid], path.name, f"[`{path.name}`](projects/{path.name}){count}"))

    def row(label: str, initiative: str | None) -> str:
        cells = [", ".join(cell for *_, cell in sorted(columns.get(initiative, {}).get(column, []))) or "—" for column in ROADMAP_COLUMNS]
        return f"| {label} | " + " | ".join(cells) + " |"

    header = "| Initiative | " + " | ".join(ROADMAP_COLUMNS) + " |\n| :--- | :--- | :--- | :--- |"
    return "\n".join([header, *(row(f"`{name}`", name) for name in order), row(NO_INITIATIVE, None)])


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
        if current.weight == "light":
            status += ", light"
        adr_cell = _lineage_link(lineage, prefix)
    return adr_cell, solution, status


def _former_note(lineage: Lineage) -> list[str]:
    former = sorted({f for rev in lineage.revisions for f in rev.fm.get("former_ids", [])})
    return ["Formerly " + ", ".join(former)] if former else []


def _relies_note(lineage: Lineage, by_id: dict[str, Lineage], prefix: str) -> list[str]:
    """What the lineage's current revision declares it relies on, each target with its state."""
    targets = [r["adr"] for r in lineage.current().fm.get("relies_on", []) if r["adr"] in by_id]
    if not targets:
        return []
    return ["Relies on " + ", ".join(f"{_lineage_link(by_id[t], prefix)} ({ADR_STATUS_DISPLAY[by_id[t].current().status].lower()})" for t in targets)]


def _pending_notes(lineage: Lineage) -> list[str]:
    """One note per revision still being worked on after the one that answers the problem, unless
    several are open with nothing decided, which the Status cell already says."""
    open_revisions = [r for r in lineage.revisions if r.status in ("working", "approved")]
    decided = any(r.status in ("accepted", "retired") for r in lineage.revisions)
    if not decided and len(open_revisions) > 1:
        return []
    return [f"Revision {r.label} {ADR_STATUS_DISPLAY[r.status].lower()}" for r in lineage.pending_successors()]


def render_decisions_by_number(root: Path = ROOT, prefix: str = "decisions/") -> str:
    """Every lineage in number order, one short row each, for finding an ADR by the number
    something else cites. A merged lineage's old number is in its Notes. `prefix` is the path
    from the file this renders into to docs/decisions/."""
    lineages = load_lineages(root)
    if not lineages:
        return "No decision lineages yet."
    by_id = {lineage.id: lineage for lineage in lineages}
    rows = []
    for lineage in lineages:
        current = lineage.current()
        adr_cell, _, status = _adr_solution_cells(lineage, prefix)
        notes = "; ".join([*_pending_notes(lineage), *_relies_note(lineage, by_id, prefix), *_former_note(lineage)])
        topic = TOPICS.get(current.fm["topic"], current.fm["topic"])
        rows.append(f"| {adr_cell} | {_cell(current.fm['short'])} | {status} | {topic} | {_cell(notes) or '—'} |")
    header = "| ADR | Decision | Status | Topic | Notes |\n| :--- | :--- | :--- | :--- | :--- |"
    return "\n".join([header, *rows])


def render_lineages_index(root: Path = ROOT, prefix: str = "decisions/") -> str:
    """The lineages grouped by topic, with the problem and solution of each. `prefix` is the
    path from the file this renders into to docs/decisions/."""
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
            adr_cell, solution, status = _adr_solution_cells(lineage, prefix)
            notes = _pending_notes(lineage)
            if lineage.id in narrowed_by:
                notes.append("Narrowed by " + ", ".join(_lineage_link(by_id[i], prefix) for i in sorted(narrowed_by[lineage.id])))
            notes.extend(_relies_note(lineage, by_id, prefix))
            if lineage.id in related:
                notes.append("Related: " + ", ".join(_lineage_link(by_id[i], prefix) for i in sorted(related[lineage.id])))
            notes.extend(_former_note(lineage))
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


def _implementing_projects(root: Path) -> dict[str, list[str]]:
    """`ADR-NNNN/label` -> the project docs that name it in `decision:` or `also_implements:`, by file name."""
    named: dict[str, list[str]] = {}
    for path, fm in sorted(((p, read_frontmatter(p)) for p in docs_in(root / "docs/projects")), key=lambda item: item[0].name):
        for ref in [*([fm["decision"]] if "decision" in fm else []), *fm.get("also_implements", [])]:
            named.setdefault(ref, []).append(path.name)
    return named


def render_open_decisions(root: Path = ROOT, prefix: str = "decisions/", project_prefix: str = "projects/") -> str:
    """Every `approved` or `working` revision, approved first, each group in lineage order,
    with the projects that implement it. Unlike the awaiting-a-project view this lists the
    covered ones too, so it is the whole set of decisions still open."""
    named = _implementing_projects(root)
    entries = []
    for lineage in load_lineages(root):
        for rev in lineage.revisions:
            if rev.status not in ("working", "approved"):
                continue
            projects = ", ".join(f"[`{n}`]({project_prefix}{n})" for n in named.get(f"{lineage.id}/{rev.label}", [])) or "—"
            adr_cell = f"[{lineage.number}]({prefix}{lineage.dir.name}/{rev.path.name})"
            entries.append(
                (
                    rev.status != "approved",
                    f"| {adr_cell} | {_revision_label(rev)} | {_cell(rev.fm['short'])} | {ADR_STATUS_DISPLAY[rev.status]} | {projects} |",
                )
            )
    if not entries:
        return "No decision is open."
    header = "| ADR | Revision | Decision | Status | Implemented by |\n| :--- | :--- | :--- | :--- | :--- |"
    return "\n".join([header, *(row for _, row in sorted(entries, key=lambda e: e[0]))])


def render_history(root: Path = ROOT, prefix: str = "decisions/") -> str:
    """The revisions that no longer answer their problem: superseded ones, with the revision that
    replaced them, and abandoned ones. The By number view shows only the current revision of a lineage."""
    rows = []
    for lineage in load_lineages(root):
        for rev in lineage.revisions:
            if rev.status not in ("superseded", "abandoned"):
                continue
            successor = lineage.get(rev.fm.get("superseded_by"))
            replaced_by = f"[revision {successor.label}]({prefix}{lineage.dir.name}/{successor.path.name})" if successor else "—"
            adr_cell = f"[{lineage.number}]({prefix}{lineage.dir.name}/{rev.path.name})"
            rows.append(f"| {adr_cell} | {_revision_label(rev)} | {_cell(rev.fm['short'])} | {ADR_STATUS_DISPLAY[rev.status]} | {replaced_by} |")
    if not rows:
        return "No revision has been superseded or abandoned."
    header = "| ADR | Revision | Decision | Status | Replaced by |\n| :--- | :--- | :--- | :--- | :--- |"
    return "\n".join([header, *rows])


def render_explorations_table(root: Path = ROOT) -> str:
    """Every open exploration with the date of its newest commit, oldest change first so a
    stale one leads. The one place that links an exploration: nothing else may (see
    doc_explorations.py). Renders into docs/project-planning.md, so links need the prefix."""
    entries = []
    for path, fm in load_explorations(root):
        changed = last_commit_date(root, path)
        entries.append((changed.isoformat() if changed else "", path.name, fm))
    if not entries:
        return "No exploration is open."
    rows = [f"| [`{name}`](explorations/{name}) | {_cell(fm['title'])} | {changed or '—'} |" for changed, name, fm in sorted(entries)]
    header = "| Exploration | Question | Last changed |\n| :--- | :--- | :--- |"
    return "\n".join([header, *rows])


# More projects than this at `building` or `de-risking` at once is reported (ADR 0037 revision 4).
ACTIVE_PROJECT_LIMIT = 15


def active_project_warnings(root: Path = ROOT) -> list[str]:
    active = sorted(fm["id"] for _, fm in _load_projects(root).values() if fm["status"] in ("building", "de-risking"))
    if len(active) <= ACTIVE_PROJECT_LIMIT:
        return []
    return [
        f"warning: {len(active)} projects are building or de-risking, over the limit of {ACTIVE_PROJECT_LIMIT} — finish or pause one before starting another"
    ]


def validate_adrs(root: Path = ROOT) -> None:
    """Lineage revisions are validated by load_lineages(). Reading any
    file sitting directly under docs/decisions/ fails: only lineage
    directories belong there. So do two lineage directories that share a
    number, which would otherwise be indexed side by side.
    """
    for path in docs_in(root / "docs/decisions"):
        if path.name != LEDGER:
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


def ensure_section(path: Path, heading: str, *, before: str) -> None:
    """Adds an empty `## <heading>` section ahead of `## <before>` when the file has none. A patch
    carries no generated view, so it cannot add the heading its generator fills."""
    text = path.read_text(encoding="utf-8")
    if not has_section(text, heading):
        path.write_text(text.replace(f"## {before}\n", f"## {heading}\n\nPLACEHOLDER\n\n## {before}\n", 1), encoding="utf-8")


def main() -> int:
    validate_adrs()
    planning = ROOT / "docs/project-planning.md"
    ensure_section(planning, "Roadmap", before="Super Projects")
    regenerate(planning, "Roadmap", render_roadmap_table())
    regenerate(planning, "Super Projects", render_initiatives_table())
    regenerate(planning, "Projects", render_standalone_projects_table())
    regenerate(planning, "Decisions awaiting a project", render_needs_project_table())
    regenerate(planning, "Open explorations", render_explorations_table())
    for warning in active_project_warnings(ROOT):
        print(warning, file=sys.stderr)
    index = ROOT / DECISION_INDEX
    regenerate(index, "By number", render_decisions_by_number())
    regenerate(index, "By topic", render_lineages_index())
    regenerate(index, "Open decisions", render_open_decisions())
    regenerate(index, "History", render_history())
    regenerate(ROOT / COVERAGE_RELATIVE, "Apps", render_coverage_table(ROOT))
    print(f"Regenerated docs/project-planning.md, {DECISION_INDEX}, {COVERAGE_RELATIVE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
