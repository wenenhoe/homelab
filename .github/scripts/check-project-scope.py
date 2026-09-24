#!/usr/bin/env python3
"""Fails a change that touches a project doc but strays outside that project's
`allowed_paths` — see doc_scope.py for the rule and the projects README for why.

Two modes, both read the scope from the project docs as they stood on the base:

  --staged          the commit being made: staged files against HEAD (pre-commit)
  --base REF        a pull request: the diff from the merge-base of REF and --head
  [--head REF]      (default HEAD) to --head. The merge-base, not REF itself, so a
                    branch that is behind doesn't see main's newer commits as its own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from doc_frontmatter import ROOT
from doc_git import base_project_loader, git
from doc_scope import PROJECT_DOC_RE, scope_errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--base", metavar="REF")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)

    if args.staged:
        base = "HEAD"
        changed = git(args.root, "diff", "--cached", "--name-only", "--no-renames", "-z").split("\0")
    else:
        base = git(args.root, "merge-base", args.base, args.head).strip()
        changed = git(args.root, "diff", "--name-only", "--no-renames", "-z", base, args.head).split("\0")
    changed = [c for c in changed if c]

    errors = scope_errors(changed, base_project_loader(args.root, base), args.root)
    if errors:
        for e in errors:
            print(f"::error::{e}")
        print(f"\n{len(errors)} file(s) outside the project's allowed_paths.", file=sys.stderr)
        return 1
    touched = [c for c in changed if PROJECT_DOC_RE.fullmatch(c)]
    print(
        "No project doc touched; nothing to scope."
        if not touched
        else "Every changed file is within the touched project's scope, or none of them declares one."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
