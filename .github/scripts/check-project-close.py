#!/usr/bin/env python3
"""Fails a change that deletes a project doc and leaves the revision its
`decision:` names `approved` and named by no remaining project — see
doc_close.py for the rule and ADR 0037 revision 2 for why.

Two modes, both reading the deleted doc as it stood on the base and the rest
of the docs as they stand once the change is applied:

  --staged          the commit being made: the index against HEAD (pre-commit)
  --base REF        a pull request: the diff from the merge-base of REF and --head
  [--head REF]      (default HEAD) to --head. The merge-base, not REF itself, so a
                    branch that is behind doesn't see main's newer deletions as its own.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from doc_close import close_errors
from doc_frontmatter import ROOT
from doc_git import base_project_loader, git
from doc_scope import PROJECT_DOC_RE

DOC_DIRS = ("docs/projects", "docs/decisions")


def export_docs(root: Path, tree: str, dest: Path) -> None:
    """Writes the decision and project docs of `tree` under `dest`, so the rule can
    read the post-change state with the same loaders the drift check uses."""
    dirs = [d for d in DOC_DIRS if git(root, "ls-tree", "--name-only", tree, f"{d}/").strip()]
    if not dirs:
        return
    archive = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", tree, "--", *dirs], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data")


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
        deleted = git(args.root, "diff", "--cached", "--name-only", "--diff-filter=D", "--no-renames", "-z").split("\0")
    else:
        base = git(args.root, "merge-base", args.base, args.head).strip()
        deleted = git(args.root, "diff", "--name-only", "--diff-filter=D", "--no-renames", "-z", base, args.head).split("\0")
    deleted = [d for d in deleted if PROJECT_DOC_RE.fullmatch(d)]
    if not deleted:
        print("No project doc deleted; nothing to close-check.")
        return 0

    result = git(args.root, "write-tree").strip() if args.staged else args.head
    with tempfile.TemporaryDirectory() as tmp:
        export_docs(args.root, result, Path(tmp))
        try:
            errors = close_errors(deleted, base_project_loader(args.root, base), Path(tmp))
        except SystemExit as exc:  # a doc in the result that doesn't parse: the drift check names it properly
            print(f"::error::the docs after this change don't parse, so the close can't be judged: {str(exc).replace(f'{tmp}/', '')}")
            return 1
    if errors:
        for e in errors:
            print(f"::error::{e}")
        print(f"\n{len(errors)} deleted project doc(s) would leave their decision unaccepted and unnamed.", file=sys.stderr)
        return 1
    print("Every deleted project doc's decision is accepted or still named by another project.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
