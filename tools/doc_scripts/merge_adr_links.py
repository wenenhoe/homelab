#!/usr/bin/env python3
"""Prepares the inbound side of merging decision lineages into a new one
(ADR 0037 revision 4; docs/decisions/README.md#compacting-accepted-records).

Merging is the maintainer's operation. The maintainer writes the new lineage
first, with every source's id in its `former_ids`; this tool then rewrites what
points at the sources, in every tracked or new text file but the sources, the
new lineage and the generated views, and changes nothing else:

- a link to a source revision now goes to the new lineage's revision 0;
- `ADR NNNN` and `ADR-NNNN` for a source number, in prose, comments and link
  text, name the new number, and a link's short name is the new lineage's;
- `ADR-NNNN/LABEL` in a project's `decision:` or `also_implements:` names the
  new lineage's revision 0;
- `related:` and `narrows:` of other records name the new lineage, once.

It does not delete the sources, regenerate the views or commit. It prints what
a person must still act on, so none of it is found late:

- the revisions whose frozen sections changed, as `Editorial-Fix:` trailers to
  put on a commit of the change;
- the project docs whose frontmatter or stage table changed, which makes the
  change work that project: every changed file must be inside its
  `allowed_paths`, read from the base branch, so widen them in an earlier change;
- lists and ranges (`ADRs A through B`) that may now read wrong;
- references left in the new lineage, which the tool never edits.

Usage:
    cd tools && python3 -m doc_scripts.merge_adr_links NEW SOURCE [SOURCE ...] [--dry-run]

NEW and each SOURCE are a lineage number (0111) or its directory name.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from doc_scripts.doc_frontmatter import REVISION_LABEL, REVISION_PATH_RE, ROOT, Lineage, load_lineages
from doc_scripts.doc_frozen import HELD_STATUSES, changed_parts, split
from doc_scripts.doc_retired import find_hits, tracked_text_files
from doc_scripts.doc_scope import PROJECT_DOC_RE, is_worked

VIEWS = ("docs/projects/README.md", "docs/project-planning.md", "docs/decisions/README.md")
_RELATED_RE = re.compile(r"^related:[^\n]*(?:\n[ \t]*-[^\n]*)*\n?", re.MULTILINE)
_NARROWS_RE = re.compile(r"^(narrows: )(ADR-\d{4})", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A(---\n)(.*?\n)(---\n)", re.DOTALL)
_ID_RE = re.compile(r"ADR-\d{4}")


_BEFORE_RANGE_RE = re.compile(r"(?:\bADRs|\b(?:through|to))\s*\[?(?:ADR[ -])?$")
_AFTER_RANGE_RE = re.compile(r"(?:\][^\s]*)?\)?(?:'s)?\s+(?:through|to)\s+\[?(?:ADR[ -])?\d{4}")


def _in_list_or_range(text: str, offset: int) -> bool:
    """Whether the number at `offset` is one of several named after `ADRs`, or an end of `A through B`,
    in prose or as link text, which a replacement can leave reading wrong."""
    before = re.sub(r"\s+", " ", text[max(0, offset - 80) : offset])
    after = re.sub(r"\s+", " ", text[offset + 4 : offset + 160])
    return bool(_BEFORE_RANGE_RE.search(before) or _AFTER_RANGE_RE.match(after))


@dataclass
class Plan:
    new: str
    sources: tuple[str, ...]
    edits: dict[str, str] = field(default_factory=dict)  # path -> text after
    frozen: list[str] = field(default_factory=list)  # revisions whose frozen sections change
    worked_projects: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)  # lists and ranges that were rewritten
    left: list[str] = field(default_factory=list)  # references the tool did not rewrite


def _find(lineages: list[Lineage], ident: str) -> Lineage:
    number = ident[:4]
    for lineage in lineages:
        if lineage.number == number and ident in (number, lineage.dir.name):
            return lineage
    raise ValueError(f"no decision lineage matches '{ident}'")


def _fix_frontmatter(text: str, new_id: str, source_ids: set[str]) -> str:
    """`related:` and `narrows:` with the sources replaced by the new lineage."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return text
    fm = m.group(2)

    def related(found: re.Match[str]) -> str:
        original = _ID_RE.findall(found.group(0))
        if not source_ids & set(original):
            return found.group(0)
        mapped = [new_id if i in source_ids else i for i in original]
        return f"related: [{', '.join(i for n, i in enumerate(mapped) if i not in mapped[:n])}]\n"

    fm = _RELATED_RE.sub(related, fm)
    fm = _NARROWS_RE.sub(lambda n: n.group(1) + (new_id if n.group(2) in source_ids else n.group(2)), fm)
    return text if fm == m.group(2) else m.group(1) + fm + text[m.end(2) :]


def plan_merge(root: Path, new: str, sources: list[str]) -> Plan:
    lineages = load_lineages(root)
    new_lineage = _find(lineages, new)
    source_lineages = [_find(lineages, s) for s in sources]
    if new_lineage in source_lineages:
        raise ValueError(f"ADR {new_lineage.number} is both the new lineage and a source")
    new_id = new_lineage.id
    source_ids = {s.id for s in source_lineages}
    listed = {i for rev in new_lineage.revisions for i in rev.fm.get("former_ids", [])}
    if missing := sorted(source_ids - listed):
        raise ValueError(f"{new_id} must list {', '.join(missing)} in `former_ids` before its sources are merged into it")
    short = new_lineage.revisions[-1].fm["short"]
    new_dir = new_lineage.dir.name
    retired = {s.number: (f"merged into ADR {new_lineage.number}", new_lineage.number) for s in source_lineages}
    source_dirs = [s.dir.name for s in source_lineages]
    dir_alternatives = "|".join(map(re.escape, source_dirs))
    path_re = re.compile(rf"(?<![\w-])(?:{dir_alternatives})/revision-\d{{3}}(?:-[a-z])?\.md")
    label_re = re.compile(rf"\b(?:{'|'.join(sorted(source_ids))})/{REVISION_LABEL}(?![\w-])")
    short_re = re.compile(rf"(\[ADR\s+{new_lineage.number}(?:\s+revision\s+[\w-]+)?)\s+\([^()\]]+\)\](?=\([^)]*{re.escape(new_dir)})")
    plan = Plan(new_lineage.number, tuple(s.number for s in source_lineages))

    for rel, text in tracked_text_files(root):
        if rel in VIEWS or any(rel.startswith(f"docs/decisions/{d}/") for d in source_dirs):
            continue
        if rel.startswith(f"docs/decisions/{new_dir}/"):
            plan.left.extend(f"{rel}:{h.line}: {h.message}" for h in find_hits(rel, text, retired))
            plan.left.extend(f"{rel}: names the source directory {d}" for d in source_dirs if d in text)
            continue
        out = path_re.sub(f"{new_dir}/revision-000.md", text)
        out = label_re.sub(f"{new_id}/0", out)
        if REVISION_PATH_RE.search(rel):
            out = _fix_frontmatter(out, new_id, source_ids)
        hits = find_hits(rel, out, retired)
        plan.review.extend(f"{rel}:{h.line}: {h.number} was in a list or range" for h in hits if h.listed or _in_list_or_range(out, h.offset))
        for hit in reversed(hits):
            out = out[: hit.offset] + new_lineage.number + out[hit.offset + 4 :]
        out = short_re.sub(lambda m: f"{m.group(1)} ({short})]", out)
        plan.left.extend(f"{rel}:{h.line}: {h.message}" for h in find_hits(rel, out, retired))
        plan.left.extend(f"{rel}: still names the source directory {d}" for d in source_dirs if d in out)
        if out == text:
            continue
        plan.edits[rel] = out
        if REVISION_PATH_RE.search(rel) and split(text)[0].get("status") in HELD_STATUSES and changed_parts(text, out):
            plan.frozen.append(rel)
        if PROJECT_DOC_RE.fullmatch(rel) and is_worked(text, out):
            plan.worked_projects.append(rel)
    return plan


def apply_plan(root: Path, plan: Plan) -> None:
    for rel, text in plan.edits.items():
        (root / rel).write_text(text, encoding="utf-8")


def report(plan: Plan, dry_run: bool = False) -> str:
    lines = [f"{'Would rewrite' if dry_run else 'Rewrote'} {len(plan.edits)} file(s) so that ADR {', ADR '.join(plan.sources)} point at ADR {plan.new}:"]
    lines += [f"  {rel}" for rel in plan.edits]
    if plan.frozen:
        lines += ["", "Frozen sections changed. Put these trailers on a commit of the change, or the accepted-records check fails the pull request:"]
        lines += [f"Editorial-Fix: {rel}" for rel in plan.frozen]
    if plan.worked_projects:
        lines += [
            "",
            "These project docs changed in their frontmatter or stage table, which works the project.",
            "Every changed file must be inside its allowed_paths on the base branch; widen them in an earlier change:",
        ]
        lines += [f"  {rel}" for rel in plan.worked_projects]
    if plan.review:
        lines += ["", "A number in a list or range was replaced; check that it still reads right:"]
        lines += [f"  {item}" for item in plan.review]
    if plan.left:
        lines += ["", "Not rewritten; edit by hand:"]
        lines += [f"  {item}" for item in plan.left]
    lines += [
        "",
        "Still to do: delete the source directories, run generate-doc-indexes twice, then pre-commit.",
        "A prose edit in a generated view goes first in its own `git am` run.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("new", help="the new lineage: its number or directory name")
    ap.add_argument("sources", nargs="+", help="the lineages merged into it")
    ap.add_argument("--dry-run", action="store_true", help="print the report and write nothing")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)
    try:
        plan = plan_merge(args.root, args.new, args.sources)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not args.dry_run:
        apply_plan(args.root, plan)
    print(report(plan, args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
