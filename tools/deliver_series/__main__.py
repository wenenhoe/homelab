"""python3 -m deliver_series PLAN [--repo DIR] [--out DIR] [--base BRANCH] [--after SERIES]... [--patches-read | --build-only]

Check the commits above `origin/<base>`, write the series file `land_series` reads, replay it on a fresh clone of the base, run the push
stage of each pull request, and print what to hand the maintainer. PLAN is a file, or `-` for standard input,
with one line per layer, in order: `<slug> <number of commits> [<title>]`. A layer of one commit may leave out its title.

A commit on the stop list is replayed only with --patches-read, which says its patch was read. Hooks whose need the machine lacks are skipped
and named. --build-only stops after the series file is written, with nothing replayed.

Numbering starts at 0001, or after the highest number in the series files named by --after, which are the ones not merged yet.
The series file is written in --out, a new directory when not given, and never inside the checkout.
Runs only where CLAUDE_CODE_REMOTE is `true`.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from deliver_series import handover
from deliver_series.build import BuildError, assign, check_form, write
from deliver_series.needs import Probe, skipped
from deliver_series.plan import PlanError, check_numbers, numbering_after, parse_plan
from deliver_series.probes import real
from deliver_series.repo import RepoError, changed_paths, commits_on_top, fetch_base, maintainer, require_clean, require_on_tip, rev, toplevel
from deliver_series.verify import Machine, VerifyError, make_shim, verify

TOOLS = Path(__file__).resolve().parent.parent


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


def progress(message: str) -> None:
    print(f"deliver_series: {message}", file=sys.stderr)


def deliver(argv: Sequence[str], probes: Mapping[str, Probe] | None = None) -> str:
    """Build, check and replay the series; return what to print. `probes` stand in for the machine's own."""
    parser = argparse.ArgumentParser(prog="deliver_series", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plan", help="the plan file, or - for standard input")
    parser.add_argument("--repo", type=Path, default=Path(), help="the checkout (default: the current directory)")
    parser.add_argument("--out", type=Path, help="the directory for the series file (default: a new one)")
    parser.add_argument("--base", default="main", help="the branch the series lands on (default: main)")
    stops = parser.add_mutually_exclusive_group()
    stops.add_argument("--patches-read", action="store_true", help="the patches of the commits on the stop list were read, so they may be replayed")
    stops.add_argument("--build-only", action="store_true", help="write the series file and stop: nothing is replayed")
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
    who = maintainer(checkout, ref)
    check_form(layers, who)
    if args.build_only:
        return str(write(layers, args.base, checkout, out))

    paths = {commit.sha: changed_paths(checkout, commit.sha) for layer in layers for commit in layer.commits}
    if (stops_found := handover.stop_list(layers, paths)) and not args.patches_read:
        named = "; ".join(f"{layer_id} ({', '.join(files)})" for layer_id, _, files in stops_found)
        raise Refused(f"these commits are on the stop list: {named}. Read their patches, then run again with --patches-read")
    skips = skipped(probes or real(checkout / "ansible"))
    for hook, reason in skips.items():
        progress(f"skipping {hook}: {reason}")
    unchecked = write(layers, args.base, checkout, out, suffix=".unchecked")
    with tempfile.TemporaryDirectory(prefix="deliver-series-bin-") as shim_dir:
        machine = Machine(who, skips, make_shim(Path(shim_dir)))
        verify(checkout, layers, unchecked, args.base, machine, TOOLS, unchecked.with_suffix("").with_suffix(".log"), progress, rev(checkout, ref))
    series = unchecked.rename(unchecked.with_suffix(""))
    return "\n\n".join([handover.render(series, layers, paths, skips), handover.commands()])


def main(argv: Sequence[str] | None = None, probes: Mapping[str, Probe] | None = None) -> int:
    try:
        text = deliver(sys.argv[1:] if argv is None else argv, probes)
    except (Refused, PlanError, RepoError, BuildError, VerifyError, OSError) as error:
        print(f"deliver_series: {error}", file=sys.stderr)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
