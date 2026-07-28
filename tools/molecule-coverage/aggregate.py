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

For tasks with a `when:` (per inventory.py's "when" field), task/loop
coverage alone hides another blind spot: "covered" only tells you the
condition was satisfied at least once - it says nothing about whether
you've ever confirmed what happens when it's NOT satisfied. A task that
executes every single time it's reached, in every scenario, might have a
`when:` that's effectively dead weight - nobody's ever verified the skip
path. Conversely, idempotence naturally re-runs converge a second time in
the same container, so a task that legitimately executes once (state not
yet achieved) and then correctly skips the second time (state already
matches) already exercises BOTH branches within a single scenario - a
signal the plain per-scenario classification above discards (it only
tracks the union of statuses, not "was skipped ALSO seen after being
covered"). "branch_coverage" recovers this: for any task with a `when:`,
whether it was ever observed executed (true branch) and ever observed
genuinely skipped (false branch, excluding empty-loop skips, which aren't
about the when: condition at all), across ALL raw events - not the
already-collapsed per-scenario/aggregate status - so idempotence's second
pass counts as real evidence even for a task whose aggregate_status is
"covered" because of its first pass.

NOT attempted: attributing which specific clause of a compound
`when: [a, b]` caused a skip. Ansible's callbacks only ever expose the
final combined boolean, never each clause's individual value - real
attribution would need to hook Ansible's conditional evaluator itself,
which a callback plugin can't do. The clauses are still captured
statically (inventory.py's "when" field) for context when reading a
"never negated" finding, but there's no empirical claim about which one.

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


def _branch_signals_by_key(events: list[dict]) -> dict[TaskKey, dict[str, bool]]:
    """{key: {"true": observed executed, "false": observed genuinely
    skipped}}, scanning ALL events (task-level AND item-level alike) -
    deliberately not filtered by is_item, since a per-item when: on a
    looped task only ever shows up as an item-level skip (the task-level
    aggregate can still read "covered" if any other item succeeded), and
    a plain task-level when: only ever shows up as a task-level skip.

    Does NOT exclude the empty-loop skip_reason, despite that seeming
    like the obvious thing to do (and an earlier version of this code did
    exactly that) - verified empirically that this is WRONG: when a
    looped task's when: is false AND that same condition is also why its
    loop source ends up empty (a common, natural pattern - e.g. a prior
    when:-gated task would have populated the loop var, so an unrelated
    `| default([])` silently produces an empty list once that task is
    skipped), Ansible reports skip_reason "No items in the list" - NOT
    "Conditional result was False" - even though the real cause is
    genuinely the when: condition. Confirmed this reason string is
    ambiguous in the other direction too: a loop that's independently
    empty for unrelated reasons, with when: true, reports the exact same
    "No items in the list" message. Ansible's own data can't distinguish
    these two cases, so there's no way to get this perfectly right either
    way - excluding the reason caused a real false negative (a genuine
    when:-false observation silently missing from branch_coverage,
    confirmed against this repo's own compose/tasks/cleanup.yaml); NOT
    excluding it risks an occasional false positive in the rarer
    "independently empty loop with a true when:" case. Chose to include
    it, consistent with this tool's standing principle (stage 8, stage
    9.1): missing real evidence is worse than occasionally over-crediting
    an ambiguous case.
    """
    by_key: dict[TaskKey, dict[str, bool]] = {}
    for event in events:
        key = _task_key(event)
        entry = by_key.setdefault(key, {"true": False, "false": False})
        status = event.get("status")
        if status in _EXECUTED_STATUSES:
            entry["true"] = True
        elif status == "skipped":
            entry["false"] = True
    return by_key


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


def _branch_coverage_for_task(
    key: TaskKey,
    scenario_branch_signals: dict[str, dict[TaskKey, dict[str, bool]]],
) -> dict:
    # Union across scenarios: true/false branch counts as observed if seen
    # in ANY scenario's raw events - including within a single scenario's
    # own converge-then-idempotence-re-converge sequence, since both
    # append into the same scenario's events and _branch_signals_by_key
    # scans all of them together.
    true_observed = False
    false_observed = False
    for signals_by_key in scenario_branch_signals.values():
        signals = signals_by_key.get(key)
        if signals:
            true_observed = true_observed or signals["true"]
            false_observed = false_observed or signals["false"]

    if true_observed and false_observed:
        branch_status = "both_branches"
    elif true_observed:
        branch_status = "true_only"
    elif false_observed:
        branch_status = "false_only"
    else:
        branch_status = "never_observed"

    return {
        "true_branch_observed": true_observed,
        "false_branch_observed": false_observed,
        "branch_status": branch_status,
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
    scenario_branch_signals = {
        name: _branch_signals_by_key(events) for name, events in scenario_events.items()
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
        if task.get("when"):
            task_report["branch_coverage"] = _branch_coverage_for_task(
                key, scenario_branch_signals
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
