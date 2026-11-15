"""Compares the Molecule shard table with the recorded timings and proposes a better one.

Each measured role is laid out again with the longest scenario first into the
least loaded shard, in as many shards as its total time needs to fit
--target-seconds (never more than it has scenarios, never fewer than one). A
role is reported when that layout shortens its longest leg by enough to be
worth a change (--min-gain-seconds and --min-gain-ratio, both of which must be
met), when it runs past the target as it is, or when it has more shards than
the target needs. A role whose slowest scenario alone is longer than the
target is reported with that scenario as the floor: no table gets it below.

Nothing here edits the table. With --proposal the proposed shards of the
reported roles are written to a file in the table's own format.

Usage (from tools/): python -m ci.timing.report --state FILE [--target-seconds N] [--proposal FILE]
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

from ci.output import write_summary_markdown
from ci.scope import molecule_scope, molecule_shards
from ci.scope.molecule_scope import REPO_ROOT
from ci.timing import state

DEFAULT_TARGET_SECONDS = 600
DEFAULT_MIN_GAIN_SECONDS = 30
DEFAULT_MIN_GAIN_RATIO = 0.1


@dataclass(frozen=True)
class Change:
    role: str
    current: list[list[str]]
    proposed: list[list[str]]
    current_longest: int
    proposed_longest: int
    floor: int
    why: str


def pack(seconds: dict[str, int], count: int) -> list[list[str]]:
    """Longest scenario first, each into the least loaded shard; shards ordered heaviest first."""
    shards: list[list[str]] = [[] for _ in range(count)]
    loads = [0] * count
    for name in sorted(seconds, key=lambda n: (-seconds[n], n)):
        index = min(range(count), key=lambda i: (loads[i], i))
        shards[index].append(name)
        loads[index] += seconds[name]
    ordered = sorted(zip(loads, shards, strict=True), key=lambda pair: (-pair[0], pair[1]))
    return [shard for _, shard in ordered]


def longest(shards: list[list[str]], seconds: dict[str, int]) -> int:
    return max(sum(seconds[name] for name in shard) for shard in shards)


def changes(
    recorded: dict,
    table: dict[str, list[list[str]]],
    target: int,
    min_gain_seconds: int,
    min_gain_ratio: float,
) -> list[Change]:
    out = []
    for role, entry in sorted(recorded["roles"].items()):
        seconds: dict[str, int] = entry["seconds"]
        if not seconds:
            continue
        current = table.get(role, [sorted(seconds)])
        if {name for shard in current for name in shard} != set(seconds):
            continue  # the table and the measurement describe different scenarios; the next run times it again
        wanted = max(1, min(math.ceil(sum(seconds.values()) / target), len(seconds)))
        proposed = pack(seconds, wanted)
        now, then, floor = longest(current, seconds), longest(proposed, seconds), max(seconds.values())
        gain = now - then
        if now > target and then < now and gain >= max(min_gain_seconds, min_gain_ratio * now):
            why = "longest leg is past the target"
        elif len(proposed) < len(current) and then <= target:
            why = "fewer legs fit the target"
        elif len(proposed) == len(current) and gain >= max(min_gain_seconds, min_gain_ratio * now):
            why = "legs are unevenly loaded"
        else:
            continue
        out.append(Change(role, current, proposed, now, then, floor, why))
    return out


def table_text(changed: list[Change]) -> str:
    """The proposed shards in the table's format; a role that needs one leg is a comment, since the table lists only split roles."""
    lines = []
    for change in changed:
        if len(change.proposed) == 1:
            lines.append(f"# {change.role}: one leg, remove it from the table")
            continue
        lines.append(f"{change.role}:")
        lines += [f"  - [{', '.join(shard)}]" for shard in change.proposed]
    return "\n".join(lines) + "\n" if lines else ""


def minutes(seconds: int) -> str:
    return f"{seconds // 60}m{seconds % 60:02d}s"


def markdown(recorded: dict, current_roles: list[str], changed: list[Change], target: int) -> str:
    unmeasured = sorted(set(current_roles) - set(recorded["roles"]))
    lines = ["### Molecule shard balance", ""]
    lines.append(f"{len(recorded['roles'])} of {len(current_roles)} roles measured; legs are aimed at {minutes(target)}.")
    if unmeasured:
        lines += ["", f"Not measured yet: {', '.join(unmeasured)}."]
    if not changed:
        lines += ["", "The table is within the thresholds for every measured role."]
        return "\n".join(lines) + "\n"
    lines += [
        "",
        "| Role | Legs now | Longest now | Legs proposed | Longest proposed | Slowest scenario | Why |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for change in changed:
        lines.append(
            f"| {change.role} | {len(change.current)} | {minutes(change.current_longest)} | {len(change.proposed)} | "
            f"{minutes(change.proposed_longest)} | {minutes(change.floor)} | {change.why} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--target-seconds", type=int, default=DEFAULT_TARGET_SECONDS)
    parser.add_argument("--min-gain-seconds", type=int, default=DEFAULT_MIN_GAIN_SECONDS)
    parser.add_argument("--min-gain-ratio", type=float, default=DEFAULT_MIN_GAIN_RATIO)
    parser.add_argument("--proposal", type=Path)
    args = parser.parse_args(argv)
    try:
        table = molecule_shards.load_table(REPO_ROOT)
    except molecule_shards.ShardError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    recorded = state.load(args.state)
    changed = changes(recorded, table, args.target_seconds, args.min_gain_seconds, args.min_gain_ratio)
    text = markdown(recorded, molecule_scope.role_names(REPO_ROOT), changed, args.target_seconds)
    print(text)
    write_summary_markdown(text)
    if args.proposal and changed:
        args.proposal.write_text(table_text(changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
