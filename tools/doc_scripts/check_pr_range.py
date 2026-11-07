#!/usr/bin/env python3
"""Runs the pull-request checks over the commits a push adds, before CI does.

CI's project-checks job runs check_project_scope, check_project_close,
check_project_start and check_accepted_records with `--base` over the whole
pull request. The commit-time hooks run the same four with `--staged`, which
sees one commit at a time: a stray file in an earlier commit of the branch, or
an `Editorial-Fix:` trailer that is written after the hook runs, is judged
only here. This is the pre-push hook that runs the `--base` forms against the
default branch.

The base is the default branch as the clone knows it, the remote's HEAD
(`origin/HEAD`) or else `origin/main`, `origin/master`, `main`, `master`. It
is not fetched, and the checks read the merge-base, so a stale one still gives
the branch's own commits. The head is the commit being pushed (pre-commit sets
`PRE_COMMIT_TO_REF`), else HEAD. When no base is found, or the head shares no
history with it (a shallow clone, such as CI's ansible-lint job), the checks
are skipped with a message and CI judges the pull request.

Usage:
    cd tools && python3 -m doc_scripts.check_pr_range [--base REF] [--head REF]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from doc_scripts import check_accepted_records, check_project_close, check_project_scope, check_project_start
from doc_scripts.doc_frontmatter import ROOT

CHECKS = (check_project_scope, check_project_close, check_project_start, check_accepted_records)


def _git(root: Path, *args: str) -> str | None:
    """Stdout of a git command, or None when it fails."""
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def default_branch(root: Path, remote: str = "origin") -> str | None:
    """The ref of the default branch in this clone, or None."""
    remote_head = _git(root, "symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD")
    candidates = [remote_head] if remote_head else []
    candidates += [f"{remote}/main", f"{remote}/master", "main", "master"]
    return next((c for c in candidates if _git(root, "rev-parse", "--verify", "--quiet", f"{c}^{{commit}}")), None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="the ref the pull request would target (default: the default branch)")
    ap.add_argument("--head", default=os.environ.get("PRE_COMMIT_TO_REF") or "HEAD")
    ap.add_argument("--remote", default=os.environ.get("PRE_COMMIT_REMOTE_NAME") or "origin")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)

    if set(args.head) == {"0"}:
        print("A ref is being deleted; there is no change to check.")
        return 0
    base = args.base or default_branch(args.root, args.remote)
    if base is None:
        print(f"No default branch found in this clone ({args.remote}/HEAD, {args.remote}/main, main); the pull-request checks were skipped and CI runs them.")
        return 0
    merge_base = _git(args.root, "merge-base", base, args.head)
    if merge_base is None:
        print(f"{args.head} shares no history with {base} (a shallow clone?); the pull-request checks were skipped and CI runs them.")
        return 0
    if merge_base == _git(args.root, "rev-parse", f"{args.head}^{{commit}}"):
        print(f"{args.head} adds no commit to {base}; nothing to check.")
        return 0

    print(f"Checking {args.head} against {base} as CI's project-checks job does.")
    failed = [check.__name__.rsplit(".", 1)[-1] for check in CHECKS if check.main(["--base", base, "--head", args.head, "--root", str(args.root)]) != 0]
    if failed:
        print(f"\nFailed: {', '.join(failed)}. CI would fail the pull request on the same.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
