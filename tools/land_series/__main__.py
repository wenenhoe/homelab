"""python3 -m land_series FILE... [--repo DIR] [--base REF] [--no-fetch] [--check COMMAND]... [--dry-run | --land [--yes]]

Replay the series in FILE... (several files make one series) on a scratch worktree of the base branch and run the
checks after every commit, then keep a local branch per pull request for review (`--dry-run` keeps none). `--land` pushes the
kept branches, opens a pull request for each, waits for its checks and merges it once the maintainer confirms (`--yes`
confirms every merge). Without --check the checks are the project scope check against the base and
`pre-commit run --all-files`; hooks to skip are named in SKIP in the environment, which the apply hooks read too.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path

from land_series.kept import KeptError, branch_of, keep, leftovers
from land_series.land import Landed, LandError, fetch, land
from land_series.manifest import Layer, Pull, SeriesError, order_layers, parse_series
from land_series.replay import Check, ReplayError, replay

DEFAULT_BASE = "origin/main"
REMOTE = "origin"


def default_checks(base: str) -> list[Check]:
    return [
        Check(("uv", "run", "python", "-m", "doc_scripts.check_project_scope", "--base", base), cwd="tools"),
        Check(("pre-commit", "run", "--all-files")),
    ]


def ask(layer: Layer, paths: Sequence[str]) -> bool:
    """Ask on the terminal; with no terminal to ask on, refuse."""
    if not sys.stdin.isatty():
        return False
    print(f"Commit {layer.id} ({layer.subject}) changes code the replay and the checks run on this machine:")
    for path in paths:
        print(f"  {path}")
    return input("Read the patch, then type 'yes' to replay it: ").strip() == "yes"


def ask_merge(pull: Pull, url: str) -> bool:
    """Ask on the terminal before a merge; with no terminal to ask on, refuse."""
    if not sys.stdin.isatty():
        return False
    commits = f", {len(pull.layers)} commits" if len(pull.layers) > 1 else ""
    print(f"Pull request {pull.number} ({pull.title}{commits}): its checks passed.\n  {url}")
    return input("Review it, then type 'yes' to merge: ").strip() == "yes"


def say(message: str) -> None:
    """Progress goes to stderr as it happens, so a long check or a CI wait is not silence."""
    print(message, file=sys.stderr, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="land_series", description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--repo", type=Path, default=Path())
    parser.add_argument("--base", default=DEFAULT_BASE, help="the branch to land on: origin/main (the default), or a name like develop for origin/develop")
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--check", action="append", default=[], metavar="COMMAND")
    parser.add_argument("--dry-run", action="store_true", help="replay and check only; leave no branches")
    parser.add_argument("--land", action="store_true", help="push the kept branches, open, wait for and merge a pull request per number")
    parser.add_argument("--yes", action="store_true", help="with --land, merge without asking after each pull request's checks pass")
    args = parser.parse_args(argv)
    if "/" not in args.base:
        args.base = f"{REMOTE}/{args.base}"
    if args.land and args.dry_run:
        parser.error("--land lands the branches a replay kept, so it cannot be combined with --dry-run")
    try:
        layers = order_layers([layer for path in args.files for layer in parse_series(path.read_bytes(), path.name)])
        if not args.no_fetch:
            fetch(args.repo, args.base)
        if args.land:
            landed = land(args.repo, layers, lambda pull, url: args.yes or ask_merge(pull, url), base=args.base, progress=say)
            return report(landed)
        checks = [Check(tuple(shlex.split(command))) for command in args.check] or default_checks(args.base)
        results = replay(args.repo, layers, checks, ask, base=args.base, progress=say)
        kept = [] if args.dry_run else keep(args.repo, results)
    except LandError as error:
        report(error.landed)
        print(f"land_series: {error}", file=sys.stderr)
        return 1
    except (SeriesError, ReplayError, KeptError, OSError) as error:
        print(f"land_series: {error}", file=sys.stderr)
        return 1
    for result in results:
        status = "already in " + args.base if not result.applied else "replayed" if args.dry_run else f"kept as {branch_of(result.layer)}"
        print(f"{result.layer.id}  {status}  {result.layer.subject}")
    if kept:
        print("Review the branches, then run again with --land to push them.")
        stale = leftovers(args.repo, [result.layer for result in results if result.applied])
        if stale:
            print(f"Left from an earlier run, not in this series: {', '.join(stale)}\nDelete each with `git branch -D <branch>` once you no longer need it.")
    return 0


def report(landed: Sequence[Landed]) -> int:
    for item in landed:
        print(f"{item.pull.number}  {'merged' if item.merged else 'left open'}  {item.url}")
        if item.kept_branch:
            print(f"  {item.kept_branch} is checked out here, so it was kept; switch to another branch, then `git branch -D {item.kept_branch}`")
    if landed and not landed[-1].merged:
        print(f"land_series: stopped before merging pull request {landed[-1].pull.number}; run it again to continue from there", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
