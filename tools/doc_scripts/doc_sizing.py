"""Size warnings for project docs (ADR 0037 revision 5): a project is the smallest unit that
closes on its own. None of these fails a check; each prompts a review for a merge or a split.

  - a single stage row, unless another project depends on this one alone;
  - more than MAX_STAGES stages;
  - a stage added to a project that was already building (`added_stage_warnings`);
  - projects that name one revision and are chained by `depends_on`, unless another project
    depends on the earlier one alone, which is a reason from outside the work;
  - a stage whose text makes it wait on another project, where `depends_on` and the planning
    view cannot see it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT, read_frontmatter
from doc_scripts.doc_scope import EXECUTION_PLAN_RE, STAGE_STATUSES, stages

MAX_STAGES = 6

# A stage that names another project (its id, its doc path, or a link to a sibling doc) and a reason to wait for it.
OTHER = r"(?:\bPROJ-[\w-]+|projects/[\w-]+\.md|\]\([\w-]+\.md\))"
WAIT_RE = re.compile(
    rf"(?:\b(?:waits?|waiting|blocked|depends?)\s+(?:on|for|until)\b[^|.]*{OTHER})"
    rf"|(?:\b(?:after|once|until|when)\b[^|.]*{OTHER}[^|.]*\b(?:closes?|is done|are done|lands?|merges?|finish\w*|complete\w*|builds?)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Project:
    path: str
    fm: dict
    rows: list[tuple[str, str]]
    text: str

    @property
    def id(self) -> str:
        return self.fm["id"]

    @property
    def deps(self) -> list[str]:
        return [dep["project"] for dep in self.fm.get("depends_on") or []]


def load_projects(root: Path = ROOT) -> list[Project]:
    found = []
    for path in sorted((root / "docs" / "projects").glob("*.md")):
        if path.name in ("README.md", "TEMPLATE.md"):
            continue
        text = path.read_text(encoding="utf-8")
        found.append(Project(str(path.relative_to(root)), read_frontmatter(path), stages(text), text))
    return found


def stage_lines(text: str) -> list[str]:
    """The table lines of the Execution plan that are stage rows, in order."""
    plan = EXECUTION_PLAN_RE.search(text)
    lines = plan.group(1).splitlines() if plan else []
    return [
        line for line in lines if line.startswith("|") and len(cells := [c.strip() for c in line.strip("| ").split("|")]) >= 3 and cells[2] in STAGE_STATUSES
    ]


def size_warnings(projects: list[Project]) -> list[str]:
    """Warnings for every open project; a `done` project is deleted, so none is expected."""
    sole = {dep for p in projects for dep in p.deps if len(p.deps) == 1}  # depended on, as the only dependency, by someone
    warnings = []
    for p in projects:
        if len(p.rows) == 1 and p.id not in sole:
            warnings.append(
                f"{p.path}: one stage and no project that depends on it alone — a stage of a neighbour, a single change that needs no project, or under-staged"
            )
        if len(p.rows) > MAX_STAGES:
            warnings.append(f"{p.path}: {len(p.rows)} stages, over {MAX_STAGES} — review for a split")
        for number, line in enumerate(stage_lines(p.text), 1):
            if WAIT_RE.search(line):
                warnings.append(
                    f"{p.path}: stage {number} waits on another project in prose — move it, or make the waiting stages a project that depends_on the other"
                )
    by_id = {p.id: p for p in projects}
    for p in projects:
        for dep in p.deps:
            earlier = by_id.get(dep)
            if earlier is None or not p.fm.get("decision") or p.fm.get("decision") != earlier.fm.get("decision"):
                continue
            others = [q for q in projects if q.id not in (p.id, earlier.id) and q.deps == [earlier.id]]
            if not others:
                chain = f"{p.id} and {earlier.id} name {p.fm['decision']} and are chained by depends_on"
                warnings.append(f"{p.path}: {chain} — one project unless something outside the work splits them")
    return warnings


def added_stage_warnings(path: str, before: str | None, after: str) -> list[str]:
    """A project that was already building and gains stage rows: the scope was set once, at the start."""
    if before is None:
        return []
    old, new = stages(before), stages(after)
    head = re.match(r"^---\n(.*?)\n---\n", before, re.DOTALL)
    if not head or not re.search(r"^status:\s*building\s*$", head.group(1), re.MULTILINE):
        return []
    added = [title for title, _ in new if title not in {t for t, _ in old}]
    return [f"{path}: stage added after building started ({title!r}) — review the project for a split" for title in added]
