"""The close rule for project docs: deleting one must not leave the
revision its `decision:` names `approved` and named by no project (ADR 0037
revision 2). Pure functions, shared by check-project-close.py. Field
validation lives in doc_frontmatter.py.

A finished project's doc is deleted, so the rule can't read a `done` status
off the tree; it has to see the deletion. It needs three things: which docs
the change deletes, what those docs said on the base, and what the tree
looks like once the change is applied.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from doc_frontmatter import REVISION_REF_RE, ROOT, docs_in, load_lineages, read_frontmatter
from doc_scope import PROJECT_DOC_RE


def _revision_key(ref: object) -> tuple[str, str] | None:
    m = REVISION_REF_RE.match(ref) if isinstance(ref, str) else None
    return (m.group(1), m.group(2)) if m else None


def close_errors(deleted: list[str], base_project: Callable[[str], dict | None], result_root: Path = ROOT) -> list[str]:
    """`deleted` are repo-relative posix paths the change removes. `base_project(path)`
    returns a project doc's frontmatter as it stood on the base, or None if it didn't
    exist. `result_root` holds docs/decisions and docs/projects as they stand once the
    change is applied. A deleted doc closes cleanly when its revision is then
    `accepted`, or a remaining project doc still names it in `decision:`;
    `also_implements:` gates nothing, so it never counts as naming."""
    deleted = sorted({p for p in deleted if PROJECT_DOC_RE.fullmatch(p)})
    if not deleted:
        return []
    revisions = {(lineage.id, rev.label): rev for lineage in load_lineages(result_root) for rev in lineage.revisions}
    still_named = {key for path in docs_in(result_root / "docs" / "projects") if (key := _revision_key(read_frontmatter(path).get("decision")))}
    errors = []
    for path in deleted:
        fm = base_project(path)
        key = _revision_key(fm.get("decision")) if fm else None
        if key is None:
            continue  # no decision to settle, or a malformed one the drift check reports
        rev = revisions.get(key)
        if (rev is not None and rev.status == "accepted") or key in still_named:
            continue
        ref = fm["decision"]
        state = rev.status if rev is not None else "absent"
        errors.append(
            f"{path}: deleted, but its decision {ref} is {state} afterwards and no remaining project doc names it — "
            "accept the revision in this change, or leave a project that names it (a not-started successor for whatever is unfinished)"
        )
    return errors
