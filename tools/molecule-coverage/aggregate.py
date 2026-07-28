#!/usr/bin/env python3
"""molecule-coverage: aggregation

Joins the static task inventory against the per-scenario execution/skip
events to produce a coverage report for a role: both per-scenario, and
aggregated (union) across all of its scenarios.

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

For tasks with has_loop=true (per inventory.py), the above alone hides a
real blind spot: a loop where only one of several items ever satisfies its
condition still reports task-level "covered" (Ansible's aggregate result
is ok/changed if ANY item succeeded), silently masking that the other
items never ran. Verified empirically (see the callback plugin's item
hooks) that Ansible fires a separate item_on_ok/skipped/failed event per
iteration in addition to the task-level one, and that an empty loop
(`loop: []`) fires neither - only a task-level skip with skip_reason
"No items in the list", distinguishable from a plain when:-false skip.
Looped tasks additionally get a "loop_coverage" breakdown (distinct items
ever executed vs. only ever skipped, and whether any scenario saw the loop
come back empty), aggregated as a union across scenarios the same way the
task-level status is.

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

_EMPTY_LOOP_SKIP_REASON = "No items in the list"

# Cap how many "never actually ran" item values get listed per task, so a
# huge loop (e.g. iterating hundreds of generated entries) doesn't blow up
# the report - the point is to point you at a couple of concrete examples
# to go check, not to enumerate every single one.
_MAX_SKIPPED_ITEMS_SHOWN = 10

TaskKey = tuple[str | None, int | None]


def _task_key(entry: dict) -> TaskKey:
    return (entry.get("task_file"), entry.get("task_line"))


def _item_repr(item) -> str:
    # Stable, hashable string form for dedup/display, regardless of
    # whether the item is a plain scalar or a dict/list.
    try:
        return json.dumps(item, sort_keys=True)
    except TypeError:
        return str(item)


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


def _loop_events_by_key(
    events: list[dict],
) -> dict[TaskKey, dict[str, dict[str, set[str]]]]:
    """For item-level events only, {key: {item_repr: {statuses observed}}}."""
    by_key: dict[TaskKey, dict[str, dict[str, set[str]]]] = {}
    for event in events:
        # is_item, not "item is not None": no_log redacts the item value
        # itself (to None) for BOTH item-level and task-level events on a
        # no_log'd looped task, so item-presence alone can't tell them
        # apart - is_item is set explicitly by the callback based on which
        # hook fired, regardless of whether the value survived redaction.
        if not event.get("is_item"):
            continue
        key = _task_key(event)
        item_repr = _item_repr(event.get("item"))
        by_key.setdefault(key, {}).setdefault(item_repr, set()).add(
            event.get("status", "")
        )
    return by_key


def _empty_loop_observed_by_key(events: list[dict]) -> set[TaskKey]:
    """Task keys where a task-level skip with the empty-loop skip_reason
    was seen - i.e. this scenario ran the task and its loop came back with
    zero items, as opposed to a plain when:-false skip."""
    keys: set[TaskKey] = set()
    for event in events:
        if (
            not event.get("is_item")
            and event.get("status") == "skipped"
            and event.get("skip_reason") == _EMPTY_LOOP_SKIP_REASON
        ):
            keys.add(_task_key(event))
    return keys


def _classify(statuses: set[str] | None) -> str:
    if not statuses:
        return "never_observed"
    if statuses & _EXECUTED_STATUSES:
        return "covered"
    if statuses & _SKIPPED_STATUSES:
        return "skipped_only"
    return "never_observed"


def _loop_coverage_for_task(
    key: TaskKey,
    scenario_loop_events: dict[str, dict[str, dict[str, set[str]]]],
    scenario_empty_keys: dict[str, set[TaskKey]],
) -> dict:
    # Union across scenarios: an item is "observed" if it was ever
    # executed in ANY scenario, even if skipped in others - same
    # union-favors-coverage philosophy as the task-level aggregate_status.
    item_statuses: dict[str, set[str]] = {}
    for events_by_item in scenario_loop_events.values():
        for item_repr, statuses in events_by_item.get(key, {}).items():
            item_statuses.setdefault(item_repr, set()).update(statuses)

    observed_items = sorted(
        repr_ for repr_, statuses in item_statuses.items() if statuses & _EXECUTED_STATUSES
    )
    skipped_only_items = sorted(
        repr_
        for repr_, statuses in item_statuses.items()
        if statuses & _SKIPPED_STATUSES and not (statuses & _EXECUTED_STATUSES)
    )
    observed_empty_loop = any(key in keys for keys in scenario_empty_keys.values())

    truncated = len(skipped_only_items) > _MAX_SKIPPED_ITEMS_SHOWN
    return {
        "items_observed_count": len(observed_items),
        "items_skipped_only": skipped_only_items[:_MAX_SKIPPED_ITEMS_SHOWN],
        "items_skipped_only_truncated": truncated,
        "items_skipped_only_count": len(skipped_only_items),
        "observed_empty_loop": observed_empty_loop,
    }


def compute_coverage(role_data_dir: Path) -> dict:
    role_name = role_data_dir.name
    inventory = load_inventory(role_data_dir)
    scenario_events = load_scenario_events(role_data_dir)
    scenario_statuses = {name: _statuses_by_key(events) for name, events in scenario_events.items()}
    scenario_loop_events = {
        name: _loop_events_by_key(events) for name, events in scenario_events.items()
    }
    scenario_empty_keys = {
        name: _empty_loop_observed_by_key(events) for name, events in scenario_events.items()
    }

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

        task_report = {
            **task,
            "per_scenario": per_scenario,
            "aggregate_status": aggregate_status,
        }
        if task.get("has_loop"):
            task_report["loop_coverage"] = _loop_coverage_for_task(
                key, scenario_loop_events, scenario_empty_keys
            )
        tasks_report.append(task_report)

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
