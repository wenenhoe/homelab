#!/usr/bin/env python3
"""Holds accepted decision records still: a change may shorten an `accepted` or
`superseded` revision but not alter what it decided, and a lineage that held one
may leave the tree only by being merged, demoted or dropped on the record — see
doc_frozen.py and doc_removed.py, and ADR 0037 revision 4 for why.

Two modes:

  --staged          the commit being made: the index against HEAD (pre-commit). It
                    reports a changed frozen section as a warning and never fails on
                    it, because the `Editorial-Fix:` trailer that excuses one is
                    written with the commit message, after the hook runs. A lineage
                    that leaves unaccounted for still fails.
  --base REF        a pull request: the diff from the merge-base of REF and --head
  [--head REF]      (default HEAD) to --head. The merge-base, not REF itself, so a
                    branch that is behind doesn't see main's newer docs as its own.
                    Fails on both rules; the trailers on the commits of the change
                    decide which edited revisions are declared editorial.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

from doc_scripts.check_project_close import export_docs
from doc_scripts.doc_frontmatter import LINEAGE_DIR_RE, REVISION_PATH_RE, ROOT
from doc_scripts.doc_frozen import frozen_errors, split
from doc_scripts.doc_git import file_at, git
from doc_scripts.doc_removed import removal_errors

TRAILER_RE = re.compile(r"^Editorial-Fix:[ \t]*(\S+)[ \t]*$", re.MULTILINE)


def base_lineages(root: Path, base: str) -> dict[str, set[str]]:
    """Each lineage number on `base` with the statuses of its revisions."""
    lineages: dict[str, set[str]] = {}
    for path in git(root, "ls-tree", "-r", "--name-only", base, "docs/decisions/").splitlines():
        m = REVISION_PATH_RE.search(path)
        if m and LINEAGE_DIR_RE.match(path.split("/")[2]):
            text = file_at(root, base, path)
            status = split(text)[0].get("status") if text else None
            lineages.setdefault(m.group(1), set()).add(str(status))
    return lineages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--base", metavar="REF")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)

    if args.staged:
        base, head = "HEAD", ""  # the index
        names = git(args.root, "diff", "--cached", "--name-only", "--diff-filter=M", "--no-renames", "-z").split("\0")
        editorial: set[str] = set()
        result = git(args.root, "write-tree").strip()
    else:
        base, head = git(args.root, "merge-base", args.base, args.head).strip(), args.head
        names = git(args.root, "diff", "--name-only", "--diff-filter=M", "--no-renames", "-z", base, head).split("\0")
        editorial = set(TRAILER_RE.findall(git(args.root, "log", "--format=%B", f"{base}..{head}")))
        result = head

    changes = []
    for name in names:
        if REVISION_PATH_RE.search(name):
            before, after = file_at(args.root, base, name), file_at(args.root, head, name)
            if before is not None and after is not None:
                changes.append((name, before, after))
    frozen = frozen_errors(changes, editorial)

    with tempfile.TemporaryDirectory() as tmp:
        export_docs(args.root, result, Path(tmp))
        try:
            removed = removal_errors(base_lineages(args.root, base), Path(tmp))
        except SystemExit as exc:  # a doc in the result that doesn't parse: the drift check names it properly
            print(f"::error::the docs after this change don't parse, so the removals can't be judged: {str(exc).replace(f'{tmp}/', '')}")
            return 1

    for e in frozen:
        print(f"::{'warning' if args.staged else 'error'}::{e}")
    for e in removed:
        print(f"::error::{e}")
    failures = removed if args.staged else [*frozen, *removed]
    if failures:
        print(f"\n{len(failures)} accepted record(s) changed or removed without a record of it.", file=sys.stderr)
        return 1
    print("Accepted records keep what they decided, and every removed lineage is accounted for.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
