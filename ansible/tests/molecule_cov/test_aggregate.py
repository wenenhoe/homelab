"""Unit tests for molecule_cov.aggregate.compute_coverage().

Fixture events are hand-built to match callback_plugins/molecule_coverage.py's
_write_event() schema exactly (scenario/role/task_name/task_file/task_line/
action/status/host/is_item/item/skip_reason/timestamp) - see that function's
docstring for field semantics. This is schema-accurate, not captured from a
real `molecule test` run (no Docker/network access in this environment) -
see the PR description for that trade-off.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MOLECULE_COVERAGE_DIR = Path(__file__).resolve().parent.parent.parent / "molecule-coverage"
sys.path.insert(0, str(MOLECULE_COVERAGE_DIR))

from molecule_cov import aggregate as agg  # noqa: E402

TASK_FILE = "/repo/ansible/roles/sample/tasks/main.yaml"


def _task(line: int, name: str, *, has_loop: bool = False, when: list[str] | None = None) -> dict:
    return {
        "task_name": name,
        "task_file": TASK_FILE,
        "task_line": line,
        "action": "ansible.builtin.debug",
        "has_loop": has_loop,
        "when": when,
    }


def _event(
    line: int,
    status: str,
    *,
    scenario: str = "default",
    is_item: bool = False,
    item=None,
    skip_reason: str | None = None,
) -> dict:
    return {
        "scenario": scenario,
        "role": "sample",
        "task_name": "irrelevant to aggregate.py - joined on file/line",
        "task_file": TASK_FILE,
        "task_line": line,
        "action": "ansible.builtin.debug",
        "status": status,
        "host": "instance",
        "is_item": is_item,
        "item": item,
        "skip_reason": skip_reason,
        "timestamp": "2026-01-01T00:00:00+00:00",
    }


def _write_role_data(tmp_path: Path, inventory: list[dict], events_by_scenario: dict[str, list[dict]]) -> Path:
    role_dir = tmp_path / "sample"
    role_dir.mkdir()
    (role_dir / "_inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    for scenario, events in events_by_scenario.items():
        lines = "\n".join(json.dumps(e) for e in events)
        (role_dir / f"{scenario}.jsonl").write_text(lines + "\n", encoding="utf-8")
    return role_dir


def _task_report(report: dict, line: int) -> dict:
    matches = [t for t in report["tasks"] if t["task_line"] == line]
    assert len(matches) == 1
    return matches[0]


def test_covered_task(tmp_path):
    inventory = [_task(10, "Covered task")]
    events = {"default": [_event(10, "ok")]}
    report = agg.compute_coverage(_write_role_data(tmp_path, inventory, events))
    assert _task_report(report, 10)["aggregate_status"] == "covered"
    assert report["summary"] == {
        "total": 1,
        "covered": 1,
        "skipped_only": 0,
        "never_observed": 0,
        "coverage_pct": 100.0,
    }


def test_skipped_only_task(tmp_path):
    inventory = [_task(20, "Skipped task")]
    events = {"default": [_event(20, "skipped", skip_reason="Conditional result was False")]}
    report = agg.compute_coverage(_write_role_data(tmp_path, inventory, events))
    assert _task_report(report, 20)["aggregate_status"] == "skipped_only"


def test_never_observed_task_absent_from_events(tmp_path):
    inventory = [_task(30, "Untouched task")]
    events = {"default": []}
    report = agg.compute_coverage(_write_role_data(tmp_path, inventory, events))
    assert _task_report(report, 30)["aggregate_status"] == "never_observed"


def test_covered_wins_union_across_scenarios_even_if_skipped_in_one(tmp_path):
    inventory = [_task(40, "Mixed task")]
    events = {
        "default": [_event(40, "skipped", skip_reason="Conditional result was False")],
        "other_scenario": [_event(40, "ok", scenario="other_scenario")],
    }
    report = agg.compute_coverage(_write_role_data(tmp_path, inventory, events))
    assert _task_report(report, 40)["aggregate_status"] == "covered"
    assert _task_report(report, 40)["per_scenario"] == {"default": "skipped_only", "other_scenario": "covered"}


def test_loop_with_a_partial_gap_is_still_task_level_covered_but_flagged(tmp_path):
    # The exact blind spot this tool exists to catch: task-level status
    # reads "covered" (aggregate ok because item "a" ran), but item "b"
    # never actually executed.
    inventory = [_task(50, "Looped task", has_loop=True)]
    events = {
        "default": [
            _event(50, "ok", is_item=True, item="a"),
            _event(50, "skipped", is_item=True, item="b", skip_reason="Conditional result was False"),
            _event(50, "ok"),  # the task-level aggregate event
        ]
    }
    report = agg.compute_coverage(_write_role_data(tmp_path, inventory, events))
    task = _task_report(report, 50)
    assert task["aggregate_status"] == "covered"
    assert task["loop_coverage"]["items_observed_count"] == 1
    assert task["loop_coverage"]["items_skipped_only"] == ['"b"']
    assert task["loop_coverage"]["observed_empty_loop"] is False


def test_empty_loop_is_distinguished_from_a_plain_when_false_skip(tmp_path):
    inventory = [_task(60, "Empty-loop task", has_loop=True)]
    events = {"default": [_event(60, "skipped", skip_reason="No items in the list")]}
    report = agg.compute_coverage(_write_role_data(tmp_path, inventory, events))
    loop_cov = _task_report(report, 60)["loop_coverage"]
    assert loop_cov["observed_empty_loop"] is True
    assert loop_cov["items_observed_count"] == 0
    assert loop_cov["items_skipped_only_count"] == 0


def test_branch_both_observed_within_one_scenario_idempotence_pass(tmp_path):
    # converge then a second idempotence pass in the same scenario: first
    # pass executes (state not yet achieved), second pass genuinely skips
    # (state already matches) - both branches observed from ONE scenario's
    # events, which per-scenario status alone would collapse into just
    # "covered".
    inventory = [_task(70, "Idempotent task", when=["some_var is defined"])]
    events = {
        "default": [
            _event(70, "changed"),
            _event(70, "skipped", skip_reason="Conditional result was False"),
        ]
    }
    report = agg.compute_coverage(_write_role_data(tmp_path, inventory, events))
    branch = _task_report(report, 70)["branch_coverage"]
    assert branch == {"true_branch_observed": True, "false_branch_observed": True, "branch_status": "both_branches"}


def test_branch_never_negated_when_only_ever_true(tmp_path):
    inventory = [_task(80, "Always-true task", when=["always_true_var"])]
    events = {"default": [_event(80, "ok")]}
    report = agg.compute_coverage(_write_role_data(tmp_path, inventory, events))
    assert _task_report(report, 80)["branch_coverage"]["branch_status"] == "true_only"


def test_missing_inventory_file_raises_filenotfounderror(tmp_path):
    role_dir = tmp_path / "sample"
    role_dir.mkdir()
    try:
        agg.compute_coverage(role_dir)
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
