"""Cross-document rules for decision lineages and project docs: the
invariants that hold between files rather than inside one. Pure
functions returning error strings, shared by check-doc-drift.py.
Field-level validation lives in doc_frontmatter.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from doc_frontmatter import REVISION_REF_RE, ROOT, Lineage, Revision, docs_in, load_lineages, read_frontmatter, ref_label

# A project's status fixes which state its linked decision revision must
# be in. The gate is what stops production work when a revision drops
# back to working.
PROJECT_DECISION_GATE = {
    "not-started": {"working", "approved"},
    "de-risking": {"working"},
    "building": {"approved"},
    "done": {"accepted"},
}

_ASSUMPTIONS_RE = re.compile(r"^## Assumptions\n\n(.*?)(?=\n## |\Z)", re.DOTALL | re.MULTILINE)
_BULLET_RE = re.compile(r"^- ", re.MULTILINE)


def has_open_assumptions(text: str) -> bool:
    """Every entry under `## Assumptions` is open; a resolved one is
    folded into Context and the heading is dropped once none remain.
    Presence of a bullet is the whole test.
    """
    m = _ASSUMPTIONS_RE.search(text)
    return bool(m and _BULLET_RE.search(m.group(1)))


def _supersession_errors(lineage: Lineage, rev: Revision, root: Path) -> list[str]:
    rel = rev.path.relative_to(root)
    fm = rev.fm
    errors = []
    if rev.status == "superseded":
        successor = lineage.get(fm["superseded_by"])
        if successor is None or successor.number <= rev.number:
            errors.append(f"{rel}: superseded_by {fm['superseded_by']} isn't a later revision in this lineage")
        elif successor.status not in ("accepted", "superseded"):
            errors.append(
                f"{rel}: superseded by revision {successor.label}, which is {successor.status} — a revision is only superseded once its successor is accepted"
            )
        elif ref_label(successor.fm.get("supersedes")) != rev.label:
            errors.append(f"{rel}: revision {successor.label} must declare 'supersedes: {rev.label}'")
    if "supersedes" in fm:
        target = lineage.get(fm["supersedes"])
        if target is None or target.number >= rev.number:
            errors.append(f"{rel}: supersedes {fm['supersedes']}, which isn't an earlier revision in this lineage")
        elif rev.status in ("accepted", "superseded") and (target.status != "superseded" or ref_label(target.fm.get("superseded_by")) != rev.label):
            errors.append(
                f"{rel}: is {rev.status} and supersedes revision {target.label}, so that revision must be status: superseded with 'superseded_by: {rev.label}'"
            )
    return errors


def _generation_errors(lineage: Lineage, root: Path) -> list[str]:
    """Generations run 000..NNN with no gaps. Within one, competing candidates
    are lettered a, b, c… with none missing (a lone one may be unlettered or
    `a`), and once one is chosen — approved, or beyond — every other candidate
    is abandoned: approval authorizes one design, never two."""
    rel = lineage.dir.relative_to(root)
    errors = []
    generations = sorted({r.number for r in lineage.revisions})
    if generations != list(range(len(generations))):
        errors.append(f"{rel}: revision numbers must run 000..NNN with no gaps, found {generations}")
    for generation in generations:
        candidates = [r for r in lineage.revisions if r.number == generation]
        letters = [r.candidate for r in candidates]
        if len(candidates) == 1:
            if letters[0] not in (None, "a"):
                errors.append(f"{rel}: revision {generation:03d} is the only candidate, so it is unlettered or 'a', not '{letters[0]}'")
        elif None in letters or sorted(letters) != [chr(97 + i) for i in range(len(letters))]:
            errors.append(
                f"{rel}: revision {generation:03d} has {len(candidates)} competing candidates; "
                f"each needs a letter, a, b, c… with none missing (found {letters})"
            )
        decided = [r for r in candidates if r.status in ("approved", "accepted", "superseded", "retired")]
        if len(decided) > 1:
            errors.append(f"{rel}: revision {generation:03d} has more than one decided candidate ({', '.join(r.label for r in decided)})")
        for r in candidates:
            if decided and r not in decided and r.status != "abandoned":
                errors.append(f"{r.path.relative_to(root)}: competes with {decided[0].label}, which is decided — mark this candidate abandoned")
    return errors


def lineage_errors(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    lineages = load_lineages(root)
    by_id: dict[str, Lineage] = {}
    for lineage in lineages:
        if lineage.id in by_id:
            errors.append(f"{lineage.dir.relative_to(root)}: {lineage.id} is also used by {by_id[lineage.id].dir.name}")
        by_id[lineage.id] = lineage

    former_owner: dict[str, str] = {}
    for lineage in lineages:
        rel = lineage.dir.relative_to(root)
        errors.extend(_generation_errors(lineage, root))
        accepted = [r.label for r in lineage.revisions if r.status == "accepted"]
        if len(accepted) > 1:
            errors.append(f"{rel}: revisions {accepted} are all accepted — only one may be; supersede the older one")
        for field in ("title", "topic"):
            values = {r.fm[field] for r in lineage.revisions}
            if len(values) > 1:
                errors.append(f"{rel}: '{field}' differs across revisions ({sorted(values)}) — it names the problem, so it stays the same")
        for rev in lineage.revisions:
            errors.extend(_supersession_errors(lineage, rev, root))
            rev_rel = rev.path.relative_to(root)
            narrows = rev.fm.get("narrows")
            if narrows == lineage.id:
                errors.append(f"{rev_rel}: narrows its own lineage")
            elif narrows is not None and narrows not in by_id:
                errors.append(f"{rev_rel}: narrows {narrows}, which isn't a lineage")
            for related in rev.fm.get("related", []):
                if related not in by_id:
                    errors.append(f"{rev_rel}: related {related}, which isn't a lineage")
            for former in rev.fm.get("former_ids", []):
                if former in by_id:
                    errors.append(f"{rev_rel}: former_ids lists {former}, which is still a live lineage")
                elif former_owner.setdefault(former, lineage.id) != lineage.id:
                    errors.append(f"{rev_rel}: {former} is already claimed as a former id by {former_owner[former]}")
    return errors


def open_assumption_errors(root: Path = ROOT) -> list[str]:
    errors = []
    for lineage in load_lineages(root):
        for rev in lineage.revisions:
            if rev.status in ("approved", "accepted") and has_open_assumptions(rev.path.read_text(encoding="utf-8")):
                errors.append(
                    f"{rev.path.relative_to(root)}: status: {rev.status} but still has an open Assumptions entry — "
                    "resolve every entry (fold into Context or revise the Decision) before approving"
                )
    return errors


def _cycle_errors(graph: dict[str, list[str]]) -> list[str]:
    errors = []
    state: dict[str, int] = {}  # 1 = on the current path, 2 = done

    def visit(node: str, path: list[str]) -> None:
        state[node] = 1
        for nxt in graph[node]:
            if state.get(nxt) == 1:
                errors.append("depends_on cycle: " + " -> ".join([*path[path.index(nxt) :], nxt]))
            elif nxt not in state:
                visit(nxt, [*path, nxt])
        state[node] = 2

    for node in graph:
        if node not in state:
            visit(node, [node])
    return errors


def project_errors(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    projects: dict[str, tuple[Path, dict]] = {}
    for path in docs_in(root / "docs" / "projects"):
        fm = read_frontmatter(path)
        if fm["id"] in projects:
            errors.append(f"{path.relative_to(root)}: id {fm['id']} is also used by {projects[fm['id']][0].name}")
        projects[fm["id"]] = (path, fm)

    revisions = {(lineage.id, rev.label): rev for lineage in load_lineages(root) for rev in lineage.revisions}
    graph: dict[str, list[str]] = {}
    for pid, (path, fm) in projects.items():
        rel = path.relative_to(root)
        graph[pid] = []
        for dep in fm.get("depends_on", []):
            target = dep["project"]
            if target == pid:
                errors.append(f"{rel}: depends_on itself")
            elif target not in projects:
                errors.append(
                    f"{rel}: depends_on {target}, which isn't a project doc — a finished project is deleted, so drop the dependency in the same change"
                )
            else:
                graph[pid].append(target)
        if "decision" not in fm:
            continue
        m = REVISION_REF_RE.match(fm["decision"])
        rev = revisions.get((m.group(1), m.group(2)))
        if rev is None:
            errors.append(f"{rel}: decision {fm['decision']} doesn't resolve to a lineage revision")
        elif rev.status not in PROJECT_DECISION_GATE[fm["status"]]:
            needed = " or ".join(sorted(PROJECT_DECISION_GATE[fm["status"]]))
            errors.append(f"{rel}: status: {fm['status']} needs decision {fm['decision']} to be {needed}, but it is {rev.status}")
    errors.extend(_cycle_errors(graph))
    return errors
