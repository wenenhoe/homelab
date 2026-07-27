#!/usr/bin/env python3
"""molecule-coverage: aggregation

Joins the static task inventory (stage 2) against the per-scenario
execution/skip events (stage 1) to produce a coverage report for a role:
both per-scenario, and aggregated (union) across all of its scenarios.

Join key is (task_file, task_line) - not task_name, since names aren't
guaranteed unique (loops, copy-pasted task names) and the callback plugin
records a "role : task name" context string that differs slightly from the
static inventory's bare name anyway; file/line was verified to match
exactly between the two stages.

Each task is classified, per scenario and in aggregate, as one of:
  - "covered"        - observed with status ok/changed/failed at least once
  - "skipped_only"    - only ever observed as skipped (its `when:` never
                        evaluated true in any scenario that reached it)
  - "never_observed" - not present in that scenario's JSONL at all (the
                        containing task file was never even loaded - e.g.
                        an include_tasks/include_role path not reached)

"failed" counts as covered: the task's action was attempted, which is what
task coverage is measuring - whether the underlying assertion/verify step
also caught the failure is a separate (and important) question, out of
scope here.

Usage:
    python3 aggregate.py tools/molecule-coverage/.data/caddy
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_EXECUTED_STATUSES = {"ok", "changed", "failed"}
_SKIPPED_STATUSES = {"skipped"}
# "unreachable" deliberately excluded from both: the host, not the task,
# was the problem, so it shouldn't count as evidence about the task itself.

TaskKey = tuple[str | None, int | None]


def _task_key(entry: dict) -> TaskKey:
    return (entry.get("task_file"), entry.get("task_line"))


def load_inventory(role_data_dir: Path) -> list[dict]:
    inventory_path = role_data_dir / "_inventory.json"
    if not inventory_path.is_file():
        raise FileNotFoundError(
            f"no {inventory_path} - run inventory.py for this role first"
        )
    return json.loads(inventory_path.read_text(encoding="utf-8"))


def load_scenario_events(role_data_dir: Path) -> dict[str, list[dict]]:
    scenarios: dict[str, list[dict]] = {}
    for jsonl_path in sorted(role_data_dir.glob("*.jsonl")):
        scenario_name = jsonl_path.stem
        events = []
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        scenarios[scenario_name] = events
    return scenarios


def _statuses_by_key(events: list[dict]) -> dict[TaskKey, set[str]]:
    by_key: dict[TaskKey, set[str]] = {}
    for event in events:
        key = _task_key(event)
        by_key.setdefault(key, set()).add(event.get("status", ""))
    return by_key


def _classify(statuses: set[str] | None) -> str:
    if not statuses:
        return "never_observed"
    if statuses & _EXECUTED_STATUSES:
        return "covered"
    if statuses & _SKIPPED_STATUSES:
        return "skipped_only"
    return "never_observed"


def compute_coverage(role_data_dir: Path) -> dict:
    role_name = role_data_dir.name
    inventory = load_inventory(role_data_dir)
    scenario_events = load_scenario_events(role_data_dir)
    scenario_statuses = {name: _statuses_by_key(events) for name, events in scenario_events.items()}

    tasks_report = []
    for task in inventory:
        key = _task_key(task)
        per_scenario = {
            scenario: _classify(statuses.get(key))
            for scenario, statuses in scenario_statuses.items()
        }
        # Aggregate/union: covered if covered in ANY scenario; else
        # skipped_only if skipped in any scenario that at least reached it;
        # else never_observed.
        classifications = set(per_scenario.values())
        if "covered" in classifications:
            aggregate_status = "covered"
        elif "skipped_only" in classifications:
            aggregate_status = "skipped_only"
        else:
            aggregate_status = "never_observed"

        tasks_report.append(
            {
                **task,
                "per_scenario": per_scenario,
                "aggregate_status": aggregate_status,
            }
        )

    total = len(tasks_report)
    covered = sum(1 for t in tasks_report if t["aggregate_status"] == "covered")
    skipped_only = sum(1 for t in tasks_report if t["aggregate_status"] == "skipped_only")
    never_observed = total - covered - skipped_only

    return {
        "role": role_name,
        "scenarios": sorted(scenario_events.keys()),
        "tasks": tasks_report,
        "summary": {
            "total": total,
            "covered": covered,
            "skipped_only": skipped_only,
            "never_observed": never_observed,
            "coverage_pct": round(100 * covered / total, 1) if total else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "role_data_dir",
        type=Path,
        help="Path to <coverage-dir>/<role> (containing _inventory.json and *.jsonl scenario files)",
    )
    args = parser.parse_args()

    role_data_dir = args.role_data_dir.resolve()
    if not role_data_dir.is_dir():
        print(f"error: {role_data_dir} is not a directory", file=sys.stderr)
        return 1

    try:
        report = compute_coverage(role_data_dir)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
