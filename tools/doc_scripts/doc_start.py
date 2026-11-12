"""The start rule for project docs: a project that a change adds is `not-started`
only when the decision it names is `approved`, or it names none (ADR 0037
revision 4). Pure functions, shared by check_project_start.py. Field validation
lives in doc_frontmatter.py.

A project whose decision is still `working` has nothing to build, but may exist
as a draft plan (`plan: draft`) for sizing and the roadmap (ADR 0037 revision 5);
the question stays in the decision or an exploration until it is approved. The
rule reads only the docs a change adds, so a project that was already waiting
on a `working` decision is not re-judged.
"""

from __future__ import annotations

from pathlib import Path

from doc_scripts.doc_frontmatter import REVISION_REF_RE, ROOT, load_lineages, read_frontmatter
from doc_scripts.doc_scope import PROJECT_DOC_RE


def start_errors(added: list[str], result_root: Path = ROOT) -> list[str]:
    """`added` are repo-relative posix paths the change creates. `result_root` holds the
    docs as they stand once the change is applied."""
    added = sorted({p for p in added if PROJECT_DOC_RE.fullmatch(p)})
    if not added:
        return []
    revisions = {(lineage.id, rev.label): rev for lineage in load_lineages(result_root) for rev in lineage.revisions}
    errors = []
    for path in added:
        fm = read_frontmatter(result_root / path)
        match = REVISION_REF_RE.match(fm["decision"]) if isinstance(fm.get("decision"), str) else None
        if fm["status"] != "not-started" or match is None:
            continue
        rev = revisions.get((match.group(1), match.group(2)))
        if rev is not None and rev.status != "approved" and fm.get("plan") != "draft":
            errors.append(
                f"{path}: a new project is not-started, but {fm['decision']} is {rev.status} — a project starts on an approved decision. "
                "Mark the plan as a draft (plan: draft) for the roadmap, or leave the work in the decision or an exploration until it is approved"
            )
    return errors
