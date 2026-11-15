"""Folds the timings a run measured into the recorded state.

A role is recorded only when every scenario on disk was timed once and
passed: a partial set would make a shard look faster than it is, a failed
scenario's time is the time to the failure, and a scenario timed twice means
a results file was copied or read twice and no row can be trusted. A role left out keeps its old
entry, whose fingerprint no longer matches, so the next run times it again.
Roles that no longer have Molecule scenarios are dropped.

A role named by --expect (a JSON array, the roles the run was meant to time)
that has no rows at all is reported too: its leg produced nothing.

Usage (from tools/): python -m ci.timing.merge --state FILE --results DIR --out FILE [--expect JSON]
`--results` is searched for `*.tsv` files, which `molecule-test-all.sh` writes
when MOLECULE_TIMINGS_FILE is set.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Collection
from datetime import date
from pathlib import Path

from ci.output import write_summary
from ci.scope import molecule_shards
from ci.scope.molecule_scope import REPO_ROOT, ScopeError
from ci.timing import fingerprint, state


def merge(
    recorded: dict,
    current: dict[str, str],
    on_disk: dict[str, set[str]],
    rows: list[tuple[str, str, int, str]],
    today: date,
    expected: Collection[str] = (),
) -> tuple[dict, list[str]]:
    """The new state, and a line for each role that was timed but could not be recorded."""
    measured: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for role, scenario, seconds, result in rows:
        measured[role].append((scenario, seconds, result))
    roles = {role: entry for role, entry in recorded["roles"].items() if role in current}
    problems = [f"{role}: no timings received" for role in sorted(set(expected) - set(measured)) if role in current]
    for role, results in sorted(measured.items()):
        if role not in current:
            problems.append(f"{role}: has no Molecule scenarios in this tree")
            continue
        names = [scenario for scenario, _, _ in results]
        if repeated := sorted({name for name in names if names.count(name) > 1}):
            problems.append(f"{role}: not recorded (timed more than once: {', '.join(repeated)})")
            continue
        failed = sorted(scenario for scenario, _, result in results if result != "passed")
        missing = sorted(on_disk[role] - set(names))
        if failed or missing:
            detail = [f"failed: {', '.join(failed)}"] * bool(failed) + [f"not run: {', '.join(missing)}"] * bool(missing)
            problems.append(f"{role}: not recorded ({'; '.join(detail)})")
            continue
        roles[role] = {"fingerprint": current[role], "measured": today.isoformat(), "seconds": {scenario: seconds for scenario, seconds, _ in results}}
    return {"version": state.VERSION, "roles": roles}, problems


def read_results(directory: Path) -> list[tuple[str, str, int, str]]:
    rows = []
    for path in sorted(directory.rglob("*.tsv")):
        rows += state.parse_results(path.read_text(), str(path))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expect", default="[]")
    args = parser.parse_args(argv)
    try:
        current = fingerprint.fingerprints(REPO_ROOT)
        rows = read_results(args.results)
    except (ScopeError, fingerprint.FingerprintError, state.ResultError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    on_disk = {role: molecule_shards.scenarios_on_disk(REPO_ROOT, role) for role in current}
    merged, problems = merge(state.load(args.state), current, on_disk, rows, date.today(), json.loads(args.expect))
    state.save(args.out, merged)
    for problem in problems:
        print(f"::warning::{problem}")
    if problems:
        write_summary("Molecule timings not recorded", problems)
    print(f"Recorded {len(merged['roles'])} of {len(current)} roles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
