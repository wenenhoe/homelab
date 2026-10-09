#!/usr/bin/env python3
"""Fails a change that works a project doc but strays outside that project's
`allowed_paths` — see doc_scope.py for the rule and the projects README for why.

Two modes, both read the scope from the project docs as they stood on the base:

  --staged          the commit being made: staged files against HEAD (pre-commit)
  --base REF        a pull request: the diff from the merge-base of REF and --head
  [--head REF]      (default HEAD) to --head. The merge-base, not REF itself, so a
                    branch that is behind doesn't see main's newer commits as its own.

A project binds a change only if the change works its doc (its frontmatter or
execution-plan table changes, or it is deleted), not when it merely edits the
doc's prose or links.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT
from doc_scripts.doc_git import base_project_loader, file_at, git
from doc_scripts.doc_scope import PROJECT_DOC_RE, is_worked, scope_errors


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
        changed = git(args.root, "diff", "--cached", "--name-only", "--no-renames", "-z").split("\0")
    else:
        base, head = git(args.root, "merge-base", args.base, args.head).strip(), args.head
        changed = git(args.root, "diff", "--name-only", "--no-renames", "-z", base, args.head).split("\0")
    changed = [c for c in changed if c]

    worked = lambda path: is_worked(file_at(args.root, base, path), file_at(args.root, head, path))  # noqa: E731
    errors = scope_errors(changed, base_project_loader(args.root, base), args.root, worked)
    if errors:
        for e in errors:
            print(f"::error::{e}")
        print(f"\n{len(errors)} file(s) outside the project's allowed_paths.", file=sys.stderr)
        return 1
    worked_docs = [c for c in changed if PROJECT_DOC_RE.fullmatch(c) and worked(c)]
    print(
        "No project doc worked; nothing to scope."
        if not worked_docs
        else "Every changed file is within the worked project's scope, or none of them declares one."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
