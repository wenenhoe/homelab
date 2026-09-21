"""Path scope for project work: a change that touches a project doc must stay
inside the `allowed_paths` that doc declares. Pure functions, shared by
check-project-scope.py. Field validation lives in doc_frontmatter.py.

A change is tied to a project by touching its doc, which the projects README
already requires of any PR that works a stage. A change that touches no
project doc isn't project work and isn't checked.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from doc_frontmatter import REVISION_REF_RE, ROOT

PROJECT_DOC_RE = re.compile(r"docs/projects/(?!(?:README|TEMPLATE)\.md$)[^/]+\.md")
# Bookkeeping the workflow itself produces for any project change: every project doc,
# and the generated decisions index (the generated projects index is a project doc's sibling).
IMPLICIT_PATTERNS = ("docs/projects/*.md", "docs/decisions/README.md")


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


def scope_errors(changed: list[str], base_project: Callable[[str], dict | None], root: Path = ROOT) -> list[str]:
    """`changed` are repo-relative posix paths the change touches (a rename counts as
    both paths). `base_project(path)` returns a project doc's frontmatter as it stood
    on the base of the change, or None if it didn't exist. Scope is read from the base
    so a change can't widen its own scope and then use it."""
    changed = sorted(set(changed))
    scoped = []
    for path in changed:
        if PROJECT_DOC_RE.fullmatch(path):
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
