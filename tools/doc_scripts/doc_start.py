"""The start rule for project docs: a project that a change adds is `not-started`
only when the decision it names is `approved`, or it names none (ADR 0037
revision 4). Pure functions, shared by check_project_start.py. Field validation
lives in doc_frontmatter.py.

A project whose decision is still `working` has nothing to build, but may exist
as a draft plan (`plan: draft`) for sizing and the roadmap (ADR 0037 revision 5);
the question stays in the decision or an exploration until it is approved. The
rule reads only the docs a change adds, so a project that was already waiting
on a `working` decision is not re-judged.

A project moves to `building` only once its plan is confirmed: no longer a draft,
with `allowed_paths` set and complete (suggest_project_scope.completeness_errors), and,
for a plan that was a draft, with the stage table read again against the approved
decision (ADR 0037 revision 5). While it builds, its scope may widen, in a change of
its own, but not narrow: it narrows only when the project closes. The re-reading is
shown by a change to the Execution plan, or by a `Plan-Confirmed: <path>` trailer
on a commit of the change when the table needed none.
"""

from __future__ import annotations

import re
from pathlib import Path

from doc_scripts.doc_frontmatter import REVISION_REF_RE, ROOT, load_lineages, read_frontmatter
from doc_scripts.doc_frozen import split
from doc_scripts.doc_scope import EXECUTION_PLAN_RE, PROJECT_DOC_RE

PLAN_CONFIRMED_RE = re.compile(r"^Plan-Confirmed:[ \t]*(\S+)[ \t]*$", re.MULTILINE)


def _plan_table(text: str) -> str:
    match = EXECUTION_PLAN_RE.search(text)
    return match.group(1).strip() if match else ""


def starts_building(before: str | None, after: str) -> bool:
    """Whether the change sets this project to `building`, as opposed to leaving it there."""
    return split(after)[0].get("status") == "building" and (split(before)[0] if before is not None else {}).get("status") != "building"


def building_errors(path: str, before: str | None, after: str, confirmed: set[str] | None) -> list[str]:
    """What stops one project doc moving to `building`. `before` is the doc on the base (None when
    the change adds it) and `after` as the change leaves it. `confirmed` holds the paths named by
    `Plan-Confirmed:` trailers on the change's commits; None when they are not known yet (a commit
    in the making), when the re-reading is not judged."""
    old = split(before)[0] if before is not None else {}
    new = split(after)[0]
    if old.get("status") == "building" and new.get("status") == "building":
        dropped = sorted(set(old.get("allowed_paths") or []) - set(new.get("allowed_paths") or []))
        return [f"{path}: allowed_paths drops `{entry}` — a scope narrows only when the project closes" for entry in dropped]
    if not starts_building(before, after):
        return []
    errors = []
    if new.get("plan") == "draft":
        errors.append(
            f"{path}: status: building, but plan: draft — read the stage table again against the approved decision, "
            "then set plan: confirmed or remove the field"
        )
    if not new.get("allowed_paths"):
        errors.append(f"{path}: status: building, but no allowed_paths — set the scope once, as building starts")
    if old.get("plan") == "draft" and confirmed is not None and _plan_table(before or "") == _plan_table(after) and path not in confirmed:
        errors.append(
            f"{path}: the plan was a draft and the stage table is unchanged — change it where the approved decision needs it, "
            f"or say it was read and needs none with a `Plan-Confirmed: {path}` trailer on a commit of the change"
        )
    return errors


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
