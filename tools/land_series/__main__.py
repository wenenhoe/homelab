"""python3 -m land_series FILE... [--repo DIR] [--base REF] [--no-fetch] [--check COMMAND]... [--skip-hook ID]...

Replay the series in FILE... (several files make one series) on a scratch worktree of the base branch and run the
checks after every layer. Without --check the checks are the project scope check against the base and
`pre-commit run --all-files`, with each --skip-hook id in SKIP.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from land_series.manifest import Layer, SeriesError, order_layers, parse_series
from land_series.replay import Check, ReplayError, replay

DEFAULT_BASE = "origin/main"
REMOTE = "origin"


def default_checks(base: str, skip_hooks: Sequence[str]) -> list[Check]:
    return [
        Check(("uv", "run", "python", "-m", "doc_scripts.check_project_scope", "--base", base), cwd="tools"),
        Check(("pre-commit", "run", "--all-files"), env={"SKIP": ",".join(skip_hooks)} if skip_hooks else {}),
    ]


def ask(layer: Layer, paths: Sequence[str]) -> bool:
    """Ask on the terminal; with no terminal to ask on, refuse."""
    if not sys.stdin.isatty():
        return False
    print(f"Layer {layer.id} ({layer.subject}) changes code the replay and the checks run on this machine:")
    for path in paths:
        print(f"  {path}")
    return input("Read the patch, then type 'yes' to replay it: ").strip() == "yes"


def fetch(repo: Path, base: str) -> None:
    remote, _, branch = base.partition("/")
    result = subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", remote, branch], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ReplayError(f"cannot fetch {base}: {result.stderr.strip()}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="land_series", description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--repo", type=Path, default=Path())
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--check", action="append", default=[], metavar="COMMAND")
    parser.add_argument("--skip-hook", action="append", default=[], metavar="ID")
    args = parser.parse_args(argv)
    try:
        layers = order_layers([layer for path in args.files for layer in parse_series(path.read_bytes(), path.name)])
        if not args.no_fetch:
            fetch(args.repo, args.base)
        checks = [Check(tuple(shlex.split(command))) for command in args.check] or default_checks(args.base, args.skip_hook)
        results = replay(args.repo, layers, checks, ask, base=args.base)
    except (SeriesError, ReplayError, OSError) as error:
        print(f"land_series: {error}", file=sys.stderr)
        return 1
    for result in results:
        print(f"{result.layer.id}  {'replayed' if result.applied else 'already in ' + args.base}  {result.layer.subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
