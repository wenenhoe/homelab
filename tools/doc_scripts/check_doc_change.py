#!/usr/bin/env python3
"""Runs the four checks on a change to the documentation as one command.

The scope, close, start and accepted-records checks each judge one kind of
change; they run together everywhere, so one entry point runs them. Every rule
runs even when an earlier one fails, and the exit code is non-zero if any did.

Three modes:

    --staged        what is staged, for the commit-time hook. Sees one commit.
    --base REF      the merge-base of REF and --head (default HEAD) to --head,
                    for CI's project-checks job, which judges the whole pull
                    request.
    --push          the same range as --base, for the pre-push hook: the base is
                    the default branch as the clone knows it (origin/HEAD, else
                    origin/main, origin/master, main, master; not fetched, and
                    the checks read the merge-base, so a stale one still gives
                    the branch's own commits) and the head is the commit being
                    pushed (PRE_COMMIT_TO_REF), else HEAD. A stray file in an
                    earlier commit, or an `Editorial-Fix:` trailer that is
                    written after the commit hook runs, is judged only here. It
                    is skipped with a message, and CI judges the pull request,
                    when no base is found, the head shares no history with it
                    (a shallow clone), the push adds no commit, or a ref is
                    being deleted.

Usage:
    cd tools && python3 -m doc_scripts.check_doc_change --staged
    cd tools && python3 -m doc_scripts.check_doc_change --base REF [--head REF]
    cd tools && python3 -m doc_scripts.check_doc_change --push [--head REF]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from doc_scripts import check_accepted_records, check_project_close, check_project_scope, check_project_start
from doc_scripts.doc_frontmatter import ROOT

RULES = (check_project_scope, check_project_close, check_project_start, check_accepted_records)


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


def run_rules(rule_args: list[str], root: Path) -> int:
    """Runs every rule with the arguments, and reports which failed."""
    failed = [rule.__name__.rsplit(".", 1)[-1] for rule in RULES if rule.main([*rule_args, "--root", str(root)]) != 0]
    if failed:
        print(f"\nFailed: {', '.join(failed)}.", file=sys.stderr)
        return 1
    return 0


def push_range(root: Path, head: str, remote: str) -> tuple[str, str] | str:
    """The (base, head) a push is judged on, or the message saying why it is skipped."""
    if set(head) == {"0"}:
        return "A ref is being deleted; there is no change to check."
    base = default_branch(root, remote)
    if base is None:
        return f"No default branch found in this clone ({remote}/HEAD, {remote}/main, main); the pull-request checks were skipped and CI runs them."
    merge_base = _git(root, "merge-base", base, head)
    if merge_base is None:
        return f"{head} shares no history with {base} (a shallow clone?); the pull-request checks were skipped and CI runs them."
    if merge_base == _git(root, "rev-parse", f"{head}^{{commit}}"):
        return f"{head} adds no commit to {base}; nothing to check."
    return base, head


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="judge what is staged")
    mode.add_argument("--base", help="judge the change from the merge-base of this ref and --head")
    mode.add_argument("--push", action="store_true", help="judge the commits a push adds against the default branch")
    ap.add_argument("--head", help="the end of the change (default: the ref being pushed, else HEAD)")
    ap.add_argument("--remote", default=os.environ.get("PRE_COMMIT_REMOTE_NAME") or "origin")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)

    if args.staged:
        return run_rules(["--staged"], args.root)
    head = args.head or os.environ.get("PRE_COMMIT_TO_REF") or "HEAD"
    if args.base:
        return run_rules(["--base", args.base, "--head", args.head or "HEAD"], args.root)

    span = push_range(args.root, head, args.remote)
    if isinstance(span, str):
        print(span)
        return 0
    print(f"Checking {span[1]} against {span[0]} as CI's project-checks job does.")
    code = run_rules(["--base", span[0], "--head", span[1]], args.root)
    if code:
        print("CI would fail the pull request on the same.", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
