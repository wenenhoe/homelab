"""python3 -m land_series FILE... [--repo DIR] [--base REF] [--no-fetch] [--check COMMAND]... [--dry-run [--accept-stops] | --land [--yes] [--keep]]

Replay the series in FILE... (several files make one series) on a scratch worktree of the base branch and run the
checks after every commit, then keep a local branch per pull request for review (`--dry-run` keeps none). Commits that change code the replay
runs are listed together before any check, and asked about once; `--accept-stops` answers for a dry run. `--land` pushes the
kept branches, opens a pull request for each, waits for its checks and merges it once the maintainer confirms (`--yes`
confirms every merge). Once every pull request has landed the series files are deleted (`--keep` leaves them).
Without --check the checks are the project scope check, against the state the pull request before the layer's leaves
(the base for the first), and `pre-commit run --all-files`, which is what committing runs; at each pull request's last commit the Python
unit tests run as well, when CI's `python_unit_tests` filter is true for the pull request. `--land` runs the pre-push hooks on each commit
it is about to push, which is what pushing runs, and then pushes with every hook off. Hooks to skip are named in SKIP in the environment, which
`pre-commit` reads.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path

from land_series.advice import kept_advice, replay_advice
from land_series.kept import KeptError, branch_of, keep, leftovers
from land_series.land import Landed, LandError, fetch, land
from land_series.live import LiveBlock
from land_series.manifest import Pull, SeriesError, order_layers, parse_base, parse_series
from land_series.replay import PULL_BASE, Check, ReplayError, TipCheck, replay
from land_series.review import accept, ask
from land_series.run import CommandError

DEFAULT_BASE = "origin/main"
REMOTE = "origin"


def default_checks() -> list[Check]:
    return [
        Check(("uv", "run", "python", "-m", "doc_scripts.check_project_scope", "--base", PULL_BASE), cwd="tools"),
        Check(("pre-commit", "run", "--all-files")),
    ]


def default_push_checks() -> list[Check]:
    """What a `git push` would run: the hooks of the pre-push stage over the pull request's own commits, on the commit that is sent.

    `check-doc-change-push` takes its base from the default branch unless told otherwise, which is not the branch of a series that lands on `develop`.
    """
    return [Check(("env", f"CHECK_DOC_CHANGE_BASE={PULL_BASE}", "pre-commit", "run", "--hook-stage", "pre-push", "--from-ref", PULL_BASE, "--to-ref", "HEAD"))]


def default_tip_checks() -> list[TipCheck]:
    """The Python unit tests, as CI's `python-unit-tests` job runs them, once at each pull request's last commit and only when its filter is true."""
    gate = Check(("uv", "run", "python", "-m", "ci.scope.filter_scope", "--base", PULL_BASE, "python_unit_tests"), cwd="tools")
    return [TipCheck(gate, Check(("uv", "run", "pytest", "ansible/tests/", "tools/tests/", "-n", "auto", "--dist", "worksteal")))]


def remote_branch(name: str) -> str:
    """`develop` is `origin/develop`; a name with a slash is taken as the remote branch already."""
    return name if "/" in name else f"{REMOTE}/{name}"


def base_of(files: Sequence[tuple[Path, bytes]]) -> str | None:
    """The base the series files' `# base:` lines name; files that name different ones are refused."""
    named = {path.name: base for path, data in files if (base := parse_base(data, path.name))}
    if len({remote_branch(base) for base in named.values()}) > 1:
        raise SeriesError("the series files name different bases: " + ", ".join(f"{name} says {base}" for name, base in sorted(named.items())))
    return next(iter(named.values()), None)


def ask_merge(pull: Pull, url: str, advice: Sequence[str] = ()) -> bool:
    """Ask on the terminal before a merge, after any advice on a review; with no terminal to ask on, refuse."""
    if not sys.stdin.isatty():
        return False
    commits = f", {len(pull.layers)} commits" if len(pull.layers) > 1 else ""
    print(f"Pull request {pull.number} ({pull.title}{commits}): its checks passed.\n  {url}")
    for line in advice:
        print(line)
    return input("Review it, then type 'yes' to merge: ").strip() == "yes"


def delete_landed(files: Sequence[tuple[Path, bytes]]) -> None:
    """Delete each series file that still holds what this run read, so one written again under the same name while CI ran survives."""
    for path, data in files:
        try:
            if path.read_bytes() != data:
                print(f"{path} changed during the run, so it was kept")
                continue
            path.unlink()
        except OSError as error:
            print(f"{path} could not be deleted: {error}")
        else:
            print(f"deleted {path}")


def say(message: str) -> None:
    """Progress goes to stderr as it happens, so a long check or a CI wait is not silence."""
    print(message, file=sys.stderr, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="land_series", description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--repo", type=Path, default=Path())
    parser.add_argument(
        "--base",
        help="the branch to land on, overriding the series file's `# base:` line: a name like develop for origin/develop; origin/main when neither says",
    )
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--check", action="append", default=[], metavar="COMMAND")
    parser.add_argument("--dry-run", action="store_true", help="replay and check only; leave no branches")
    parser.add_argument(
        "--accept-stops", action="store_true", help="with --dry-run on a throwaway machine, list the commits on the stop list and replay them without asking"
    )
    parser.add_argument("--land", action="store_true", help="push the kept branches, open, wait for and merge a pull request per number")
    parser.add_argument("--yes", action="store_true", help="with --land, merge without asking after each pull request's checks pass")
    parser.add_argument("--keep", action="store_true", help="with --land, keep the series files instead of deleting them once everything has landed")
    args = parser.parse_args(argv)
    display = LiveBlock(sys.stderr).show
    if args.land and args.dry_run:
        parser.error("--land lands the branches a replay kept, so it cannot be combined with --dry-run")
    if args.accept_stops and not args.dry_run:
        parser.error("--accept-stops runs the series' code without asking, so it is only taken with --dry-run")
    try:
        files = [(path, path.read_bytes()) for path in args.files]
        args.base = remote_branch(args.base or base_of(files) or DEFAULT_BASE)
        layers = order_layers([layer for path, data in files for layer in parse_series(data, path.name)])
        if not args.no_fetch:
            fetch(args.repo, args.base)
        if args.land:
            landed = land(
                args.repo,
                layers,
                lambda pull, url: args.yes or ask_merge(pull, url, kept_advice(args.repo, pull, branch_of(pull))),
                base=args.base,
                progress=say,
                display=display,
                push_checks=default_push_checks(),
            )
            status = report(landed)
            if status == 0 and not args.keep:
                delete_landed(files)
            return status
        checks = [Check(tuple(shlex.split(command))) for command in args.check] or default_checks()
        tip_checks = [] if args.check else default_tip_checks()
        results = replay(args.repo, layers, checks, accept if args.accept_stops else ask, base=args.base, progress=say, display=display, tip_checks=tip_checks)
        kept = [] if args.dry_run else keep(args.repo, results)
    except LandError as error:
        report(error.landed)
        print(f"land_series: {error}", file=sys.stderr)
        return 1
    except (SeriesError, ReplayError, KeptError, CommandError, OSError) as error:
        print(f"land_series: {error}", file=sys.stderr)
        return 1
    for result in results:
        status = "already in " + args.base if not result.applied else "replayed" if args.dry_run else f"kept as {branch_of(result.layer)}"
        print(f"{result.layer.id}  {status}  {result.layer.subject}")
    for line in replay_advice(args.repo, results):
        print(line)
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
