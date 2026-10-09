"""Path scope for project work: a change that works a project doc must stay
inside the `allowed_paths` that doc declares. Pure functions, shared by
check_project_scope.py. Field validation lives in doc_frontmatter.py.

A change is tied to a project by working its doc, which the projects README
already requires of any PR that works a stage: changing its frontmatter or its
execution-plan table, or deleting it. An edit to the doc's prose or links, such
as a wording or link sweep across every doc, doesn't tie the change to the
project. A change that works no project doc isn't project work and isn't checked.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from doc_scripts.doc_frontmatter import REVISION_REF_RE, ROOT

PROJECT_DOC_RE = re.compile(r"docs/projects/(?!(?:README|TEMPLATE)\.md$)[^/]+\.md")
# Bookkeeping the workflow itself produces for any project change: every project doc,
# and the generated views a status change regenerates (the projects index is a project
# doc's sibling; the decisions index and project-planning.md live elsewhere).
IMPLICIT_PATTERNS = ("docs/projects/*.md", "docs/decisions/README.md", "docs/project-planning.md")


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
EXECUTION_PLAN_RE = re.compile(r"^## Execution plan[ \t]*\n(.*?)(?=^## |\Z)", re.DOTALL | re.MULTILINE)


def project_state(text: str | None) -> tuple[str, tuple[str, ...]] | None:
    """What working a stage changes in a project doc: its frontmatter and the number and status
    of each row of its Execution plan table, not the wording of a stage or its exit condition.
    None when the doc doesn't exist."""
    if text is None:
        return None
    front = FRONTMATTER_RE.match(text)
    plan = EXECUTION_PLAN_RE.search(text)
    rows = []
    for line in plan.group(1).splitlines() if plan else ():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 3:
            rows.append(f"{cells[0]}|{cells[2]}")
    return (front.group(1) if front else "", tuple(rows))


def is_worked(base_text: str | None, head_text: str | None) -> bool:
    """Whether the change works this project doc, as opposed to editing its prose in passing.
    A deletion always counts: it closes the project."""
    return head_text is None or project_state(base_text) != project_state(head_text)


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """`**` crosses directories; `*` and `?` stay inside one path segment."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def matches(pattern: str, path: str) -> bool:
    return glob_to_regex(pattern).match(path) is not None


def decision_revision_path(fm: dict, root: Path) -> str | None:
    """Repo-relative path of the revision a project's `decision:` names, if it exists."""
    m = REVISION_REF_RE.match(fm.get("decision", ""))
    if not m:
        return None
    number, _, letter = m.group(2).partition("-")
    filename = f"revision-{int(number):03d}{'-' + letter if letter else ''}.md"
    found = sorted((root / "docs" / "decisions").glob(f"{m.group(1)[4:]}-*/{filename}"))
    return found[0].relative_to(root).as_posix() if found else None


def scope_errors(
    changed: list[str],
    base_project: Callable[[str], dict | None],
    root: Path = ROOT,
    worked: Callable[[str], bool] = lambda path: True,
) -> list[str]:
    """`changed` are repo-relative posix paths the change touches (a rename counts as
    both paths). `base_project(path)` returns a project doc's frontmatter as it stood
    on the base of the change, or None if it didn't exist. Scope is read from the base
    so a change can't widen its own scope and then use it. `worked(path)` says whether
    the change works that project doc (see is_worked); a doc it merely touches in
    passing binds nothing."""
    changed = sorted(set(changed))
    scoped = []
    for path in changed:
        if PROJECT_DOC_RE.fullmatch(path) and worked(path):
            fm = base_project(path)
            if fm and fm.get("allowed_paths"):
                scoped.append((path, fm))
    if not scoped:
        return []
    allowed = [glob_to_regex(p) for _, fm in scoped for p in fm["allowed_paths"]] + [glob_to_regex(p) for p in IMPLICIT_PATTERNS]
    exact = {p for _, fm in scoped if (p := decision_revision_path(fm, root))}
    owners = ", ".join(f"{fm['id']} ({path})" for path, fm in scoped)
    return [
        f"{f}: outside the allowed_paths of {owners} as they stand on the base branch — widen them in their own change first, or drop this file from the change"
        for f in changed
        if f not in exact and not any(r.match(f) for r in allowed)
    ]
