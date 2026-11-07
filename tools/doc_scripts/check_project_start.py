#!/usr/bin/env python3
"""Fails a change that adds a `not-started` project whose decision revision is not
`approved` — see doc_start.py for the rule and ADR 0037 revision 4 for why.

Two modes, both reading the docs as they stand once the change is applied:

  --staged          the commit being made: the index against HEAD (pre-commit)
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
from doc_scripts.doc_git import git
from doc_scripts.doc_scope import PROJECT_DOC_RE
from doc_scripts.doc_start import start_errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--base", metavar="REF")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)

    if args.staged:
        added = git(args.root, "diff", "--cached", "--name-only", "--diff-filter=A", "--no-renames", "-z").split("\0")
    else:
        base = git(args.root, "merge-base", args.base, args.head).strip()
        added = git(args.root, "diff", "--name-only", "--diff-filter=A", "--no-renames", "-z", base, args.head).split("\0")
    added = [a for a in added if PROJECT_DOC_RE.fullmatch(a)]
    if not added:
        print("No project doc added; nothing to start-check.")
        return 0

    result = git(args.root, "write-tree").strip() if args.staged else args.head
    with tempfile.TemporaryDirectory() as tmp:
        export_docs(args.root, result, Path(tmp))
        try:
            errors = start_errors(added, Path(tmp))
        except SystemExit as exc:  # a doc in the result that doesn't parse: the drift check names it properly
            print(f"::error::the docs after this change don't parse, so the start can't be judged: {str(exc).replace(f'{tmp}/', '')}")
            return 1
    if errors:
        for e in errors:
            print(f"::error::{e}")
        print(f"\n{len(errors)} new project doc(s) start on a decision that is not approved.", file=sys.stderr)
        return 1
    print("Every new not-started project names an approved decision, or none.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
