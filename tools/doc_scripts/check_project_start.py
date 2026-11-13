"""Fails a change that starts a project too early — see doc_start.py for the rules
and ADR 0037 revisions 4 and 5 for why:

  - adds a `not-started` project whose decision revision is not `approved`, unless
    its plan is a draft;
  - moves a project to `building` with the plan still a draft, no `allowed_paths`,
    a scope that lacks a path the plan names or a file that mentions a
    `sweep_terms` term (and is not under "Not in"), or a draft whose stage table was
    not read again (a change to it, or a `Plan-Confirmed: <path>` trailer on a
    commit of the change);
  - narrows the `allowed_paths` of a project that is building.

Two modes, both reading the docs as they stand once the change is applied:

  --staged          the commit being made: the index against HEAD (pre-commit). The
                    trailer is written with the commit message, after the hook runs,
                    so the re-reading is not judged here.
  --base REF        a pull request: the diff from the merge-base of REF and --head
  [--head REF]      (default HEAD) to --head. The merge-base, not REF itself, so a
                    branch that is behind doesn't see main's newer docs as its own.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from doc_scripts.check_project_close import export_docs
from doc_scripts.doc_frontmatter import ROOT
from doc_scripts.doc_git import file_at, git
from doc_scripts.doc_scope import PROJECT_DOC_RE
from doc_scripts.doc_start import PLAN_CONFIRMED_RE, building_errors, start_errors, starts_building
from doc_scripts.suggest_project_scope import completeness_errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--base", metavar="REF")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)

    if args.staged:
        base, head, confirmed = "HEAD", "", None  # the index
        diff = ["diff", "--cached", "--name-status", "--no-renames", "-z"]
    else:
        base, head = git(args.root, "merge-base", args.base, args.head).strip(), args.head
        confirmed = set(PLAN_CONFIRMED_RE.findall(git(args.root, "log", "--format=%B", f"{base}..{head}")))
        diff = ["diff", "--name-status", "--no-renames", "-z", base, head]
    fields = git(args.root, *diff).split("\0")
    changes = {path: status for status, path in zip(fields[0::2], fields[1::2], strict=False) if PROJECT_DOC_RE.fullmatch(path) and status in "AM"}
    added = [path for path, status in changes.items() if status == "A"]
    if not changes:
        print("No project doc added or changed; nothing to start-check.")
        return 0

    result = git(args.root, "write-tree").strip() if args.staged else args.head
    with tempfile.TemporaryDirectory() as tmp:
        export_docs(args.root, result, Path(tmp))
        try:
            errors = start_errors(added, Path(tmp))
            for path in changes:
                before, after = file_at(args.root, base, path), file_at(args.root, head, path) or ""
                errors.extend(building_errors(path, before, after, confirmed))
                if starts_building(before, after):
                    errors.extend(completeness_errors(args.root, path))
        except SystemExit as exc:  # a doc in the result that doesn't parse: the drift check names it properly
            print(f"::error::the docs after this change don't parse, so the start can't be judged: {str(exc).replace(f'{tmp}/', '')}")
            return 1
    if errors:
        for e in errors:
            print(f"::error::{e}")
        print(f"\n{len(errors)} project doc(s) start too early.", file=sys.stderr)
        return 1
    print("Every new project starts on an approved decision or as a draft, and every project that starts building has a confirmed plan and a scope.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
