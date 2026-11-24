"""python3 -m renovate_merge summary [--repo DIR] [--base BRANCH] [--out DIR] [--notes-characters N] [--allow-main]
python3 -m renovate_merge merge SUMMARY.json [PR ...] [--repo DIR] [--yes | --allow-main] [--dry-run]
python3 -m renovate_merge promote [--repo DIR] [--yes] [--dry-run]

`summary` reads Renovate's open pull requests into BRANCH (default `maintenance`), prints their updates and release notes with
the lines that look like breaking changes marked, and writes `summary.md` and `summary.json` to OUT (default: `renovate-merge/` in the
git directory). `merge` merges the pull requests of a summary.json: those named, or with none named every one at level `none`, each only
while its head is the commit the summary read and once the required checks have passed. It uses the maintainer's own `gh` login and
refuses `main` as a branch unless `--allow-main` is given to both commands; with it `merge` asks for the branch name to be typed and
refuses `--yes`. `promote` opens the pull request that promotes `maintenance` into `main`, with a table of what the batch
holds, and stops there: the merge deploys, so it is made by hand.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from land_series.run import CommandError, checked

from renovate_merge import promote, report
from renovate_merge.collect import collect
from renovate_merge.gh import GhError
from renovate_merge.merge import PROTECTED_BRANCHES, MergeError, Outcome, Reviewed, load_summary, merge, select

DEFAULT_BASE = "maintenance"
OUT_DIRECTORY = "renovate-merge"


def say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def default_out(repo: Path) -> Path:
    return Path(checked(["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"]).text) / OUT_DIRECTORY


def ask(chosen: Sequence[Reviewed], base: str) -> bool:
    """Ask on the terminal once for the whole list; with no terminal to ask on, refuse. A merge into a protected branch is confirmed by typing its name."""
    if not sys.stdin.isatty():
        return False
    answer = base if base in PROTECTED_BRANCHES else "yes"
    print(f"Merge these into {base} once their required checks pass:")
    for pull in chosen:
        print(f"  #{pull.number}  {pull.level:<8}  {pull.title}")
    return input(f"Type '{answer}' to merge them: ").strip() == answer


def summarise(args: argparse.Namespace) -> int:
    if args.base in PROTECTED_BRANCHES and not args.allow_main:
        say(f"renovate_merge: {args.base} is not read without --allow-main: a merge there can be a deploy")
        return 1
    now = datetime.now(UTC)
    pulls = collect(args.repo, args.base)
    out = args.out or default_out(args.repo)
    out.mkdir(parents=True, exist_ok=True)
    text = report.markdown(pulls, args.base, now, args.notes_characters)
    (out / "summary.md").write_text(text, encoding="utf-8")
    (out / "summary.json").write_text(report.to_json(pulls, args.base, now), encoding="utf-8")
    print(text)
    say(f"renovate_merge: wrote {out / 'summary.md'} and {out / 'summary.json'}")
    return 0


def outcomes_status(outcomes: Sequence[Outcome]) -> int:
    for item in outcomes:
        print(f"#{item.number}  {'merged' if item.merged else 'not merged: ' + item.reason}  {item.url}")
    return 0 if all(item.merged for item in outcomes) else 1


def merging(args: argparse.Namespace) -> int:
    if args.allow_main and args.yes:
        say("renovate_merge: --allow-main cannot be combined with --yes: a merge into main is confirmed by typing the branch name")
        return 1
    summary = load_summary(args.summary.read_text(encoding="utf-8"), args.allow_main)
    chosen = select(summary, args.pulls)
    confirm = (lambda _: True) if args.yes else (lambda pulls: ask(pulls, summary.base))
    outcomes = merge(args.repo, summary, chosen, confirm, dry_run=args.dry_run, progress=say)
    status = outcomes_status(outcomes)
    return 0 if args.dry_run else status


def promoting(args: argparse.Namespace) -> int:
    def ask_promote(found: promote.Batch) -> bool:
        if not sys.stdin.isatty():
            return False
        print("\n".join(promote.describe(found)))
        return input(f"Type 'yes' to open the pull request into {promote.TARGET}: ").strip() == "yes"

    found, opened = promote.promote(args.repo, (lambda _: True) if args.yes else ask_promote, dry_run=args.dry_run)
    if opened is None:
        print(f"{found.title}\n\n{promote.body(found)}")
        return 0
    if opened.created:
        print(f"Opened {opened.url}\nMerge it by hand with a merge commit, using the bypass; this tool never merges into {promote.TARGET}.")
    else:
        print(f"Already open: {opened.url}\nIts description was not changed.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="renovate_merge", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    summary = commands.add_parser("summary", help="read the open pull requests and write the summary")
    summary.add_argument("--repo", type=Path, default=Path())
    summary.add_argument("--base", default=DEFAULT_BASE)
    summary.add_argument("--out", type=Path, default=None)
    summary.add_argument("--allow-main", action="store_true", help="read pull requests into main, for a repository where a merge there deploys nothing")
    summary.add_argument("--notes-characters", type=int, default=report.DEFAULT_NOTES_CHARACTERS, help="how much of each package's release notes to print")
    merging_parser = commands.add_parser("merge", help="merge the pull requests of a summary")
    merging_parser.add_argument("summary", type=Path, help="the summary.json written by `summary`")
    merging_parser.add_argument(
        "pulls", nargs="*", type=int, metavar="PR", help="pull request numbers to merge whatever their level; none means every one at level `none`"
    )
    merging_parser.add_argument("--repo", type=Path, default=Path())
    merging_parser.add_argument("--yes", action="store_true", help="merge without asking")
    merging_parser.add_argument("--allow-main", action="store_true", help="merge a summary of main, confirmed by typing main; not with --yes")
    merging_parser.add_argument("--dry-run", action="store_true", help="report what each pull request would do and merge nothing")
    promoting_parser = commands.add_parser("promote", help="open the pull request that promotes maintenance into main")
    promoting_parser.add_argument("--repo", type=Path, default=Path())
    promoting_parser.add_argument("--yes", action="store_true", help="open it without asking")
    promoting_parser.add_argument("--dry-run", action="store_true", help="print the title and description and open nothing")
    args = parser.parse_args(argv)
    commands_run = {"summary": summarise, "merge": merging, "promote": promoting}
    try:
        return commands_run[args.command](args)
    except (promote.PromoteError, MergeError, GhError, CommandError, subprocess.SubprocessError, OSError, ValueError) as error:
        print(f"renovate_merge: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
