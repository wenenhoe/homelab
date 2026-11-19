"""python3 -m renovate_merge summary [--repo DIR] [--base BRANCH] [--out DIR] [--notes-characters N]

`summary` reads Renovate's open pull requests into BRANCH (default `maintenance`), prints their updates and release notes with
the lines that look like breaking changes marked, and writes `summary.md` and `summary.json` to OUT (default: `renovate-merge/` in the
git directory).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from land_series.run import CommandError, checked

from renovate_merge import report
from renovate_merge.collect import collect
from renovate_merge.gh import GhError

DEFAULT_BASE = "maintenance"
OUT_DIRECTORY = "renovate-merge"


def say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def default_out(repo: Path) -> Path:
    return Path(checked(["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"]).text) / OUT_DIRECTORY


def summarise(args: argparse.Namespace) -> int:
    if args.base == "main":
        say("renovate_merge: Renovate's pull requests do not target main, and this tool never merges there")
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="renovate_merge", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    summary = commands.add_parser("summary", help="read the open pull requests and write the summary")
    summary.add_argument("--repo", type=Path, default=Path())
    summary.add_argument("--base", default=DEFAULT_BASE)
    summary.add_argument("--out", type=Path, default=None)
    summary.add_argument("--notes-characters", type=int, default=report.DEFAULT_NOTES_CHARACTERS, help="how much of each pull request's release notes to print")
    args = parser.parse_args(argv)
    try:
        return summarise(args)
    except (GhError, CommandError, subprocess.SubprocessError, OSError, ValueError) as error:
        print(f"renovate_merge: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
