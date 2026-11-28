"""python3 -m deliver_series PLAN [--repo DIR] [--out DIR] [--base BRANCH] [--after SERIES]...

Check the commits above `origin/<base>` and write the series file `land_series` reads. PLAN is a file, or `-` for standard input,
with one line per layer, in order: `<slug> <number of commits> [<title>]`. A layer of one commit may leave out its title.

Numbering starts at 0001, or after the highest number in the series files named by --after, which are the ones not merged yet.
The series file is written in --out, a new directory when not given, and never inside the checkout.
Runs only where CLAUDE_CODE_REMOTE is `true`.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from deliver_series.build import BuildError, assign, check_form, write
from deliver_series.plan import PlanError, check_numbers, numbering_after, parse_plan
from deliver_series.repo import RepoError, commits_on_top, fetch_base, maintainer, require_clean, require_on_tip, toplevel


class Refused(Exception):
    """A reason the series was not built."""


def require_remote_session() -> None:
    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        raise Refused("this runs only where CLAUDE_CODE_REMOTE is `true`; it is for a session on a machine that is thrown away")


def output_directory(out: Path | None, checkout: Path) -> Path:
    """`out`, or a new directory; one inside the checkout is refused, since a series file left there is an untracked change."""
    if out is None:
        return Path(tempfile.mkdtemp(prefix="deliver-series-"))
    out = out.resolve()
    if out == checkout or checkout in out.parents:
        raise Refused(f"{out} is inside the checkout; write the series file outside it")
    if not out.is_dir():
        raise Refused(f"{out} is not a directory")
    return out


def deliver(argv: Sequence[str]) -> Path:
    parser = argparse.ArgumentParser(prog="deliver_series", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plan", help="the plan file, or - for standard input")
    parser.add_argument("--repo", type=Path, default=Path(), help="the checkout (default: the current directory)")
    parser.add_argument("--out", type=Path, help="the directory for the series file (default: a new one)")
    parser.add_argument("--base", default="main", help="the branch the series lands on (default: main)")
    parser.add_argument("--after", type=Path, action="append", default=[], help="a series file that is not merged yet; numbering follows it")
    args = parser.parse_args(argv)

    require_remote_session()
    plan_text = sys.stdin.read() if args.plan == "-" else Path(args.plan).read_text()
    layers_planned = parse_plan(plan_text)
    first, taken = numbering_after(args.after)
    check_numbers(first, layers_planned, taken)
    checkout = toplevel(args.repo)
    out = output_directory(args.out, checkout)

    require_clean(checkout)
    ref = fetch_base(checkout, args.base)
    require_on_tip(checkout, ref)
    commits = commits_on_top(checkout, ref)
    layers = assign(layers_planned, commits, first)
    check_form(layers, maintainer(checkout, ref))
    return write(layers, args.base, checkout, out)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        path = deliver(sys.argv[1:] if argv is None else argv)
    except (Refused, PlanError, RepoError, BuildError, OSError) as error:
        print(f"deliver_series: {error}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
