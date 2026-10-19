"""The close rule for project docs: deleting one must not leave a revision
it names in `decision:` or `also_implements:` unaccepted and named by no
remaining project (ADR 0037 revision 3). Pure functions, shared by
check_project_close.py. Field
validation lives in doc_frontmatter.py.

A finished project's doc is deleted, so the rule can't read a `done` status
off the tree; it has to see the deletion. It needs three things: which docs
the change deletes, what those docs said on the base, and what the tree
looks like once the change is applied.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from doc_scripts.doc_frontmatter import REVISION_REF_RE, ROOT, docs_in, load_lineages, read_frontmatter
from doc_scripts.doc_scope import PROJECT_DOC_RE


def _revision_key(ref: object) -> tuple[str, str] | None:
    m = REVISION_REF_RE.match(ref) if isinstance(ref, str) else None
    return (m.group(1), m.group(2)) if m else None


def _revision_keys(fm: dict) -> list[tuple[str, str]]:
    """The revisions a project doc names, in `decision:` first and then `also_implements:`,
    without repeats. A malformed reference is skipped; the drift check reports it."""
    refs = [fm.get("decision"), *(fm.get("also_implements") or [])]
    keys: list[tuple[str, str]] = []
    for ref in refs:
        key = _revision_key(ref)
        if key is not None and key not in keys:
            keys.append(key)
    return keys


def close_errors(deleted: list[str], base_project: Callable[[str], dict | None], result_root: Path = ROOT) -> list[str]:
    """`deleted` are repo-relative posix paths the change removes. `base_project(path)`
    returns a project doc's frontmatter as it stood on the base, or None if it didn't
    exist. `result_root` holds docs/decisions and docs/projects as they stand once the
    change is applied. A deleted doc closes cleanly when each revision it names, in
    `decision:` or `also_implements:`, is then `accepted` or still named by a remaining
    project doc in either field. `also_implements:` still gates no project's status; it
    only keeps a revision from being left behind when the project that named it closes."""
    deleted = sorted({p for p in deleted if PROJECT_DOC_RE.fullmatch(p)})
    if not deleted:
        return []
    revisions = {(lineage.id, rev.label): rev for lineage in load_lineages(result_root) for rev in lineage.revisions}
    still_named = {key for path in docs_in(result_root / "docs" / "projects") for key in _revision_keys(read_frontmatter(path))}
    errors = []
    for path in deleted:
        fm = base_project(path)
        if not fm:
            continue  # a doc the base did not have; the drift check reports a malformed one
        for key in _revision_keys(fm):
            rev = revisions.get(key)
            if (rev is not None and rev.status == "accepted") or key in still_named:
                continue
            ref = f"{key[0]}/{key[1]}"
            state = rev.status if rev is not None else "absent"
            errors.append(
                f"{path}: deleted, but {ref} is {state} afterwards and no remaining project doc names it — "
                "accept the revision in this change, or leave a project that names it (a not-started successor for whatever is unfinished)"
            )
    return errors
