"""Unit tests for molecule_cov.inventory.scan_role() and its helpers.

Exercises the fixture role at fixtures/roles/sample/tasks/main.yaml, which
was written specifically to hit every branch scan_role() has: a plain
task, single- and compound-`when:` tasks, a `loop:` task, a legacy
`with_items:` task, a block/rescue nesting, and the three
structurally-unmeasurable actions (import_tasks, meta) plus one that
IS measurable despite sounding similar (include_tasks).

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import sys
from pathlib import Path

MOLECULE_COVERAGE_DIR = Path(__file__).resolve().parent.parent.parent / "molecule-coverage"
sys.path.insert(0, str(MOLECULE_COVERAGE_DIR))

from molecule_cov import inventory as inv  # noqa: E402

FIXTURE_ROLE = Path(__file__).resolve().parent / "fixtures" / "roles" / "sample"


def _by_name(tasks: list[dict], name: str) -> dict:
    matches = [t for t in tasks if t["task_name"] == name]
    assert len(matches) == 1, f"expected exactly one task named {name!r}, found {len(matches)}"
    return matches[0]


def test_plain_task_has_no_loop_and_no_when():
    tasks = inv.scan_role(FIXTURE_ROLE)
    task = _by_name(tasks, "Plain task, no when, no loop")
    assert task["has_loop"] is False
    assert task["when"] is None
    assert task["action"] == "ansible.builtin.debug"


def test_single_when_is_normalized_to_a_one_item_list():
    tasks = inv.scan_role(FIXTURE_ROLE)
    task = _by_name(tasks, "Task with a single when clause")
    assert task["when"] == ["some_var is defined"]


def test_compound_when_keeps_each_clause_separately():
    tasks = inv.scan_role(FIXTURE_ROLE)
    task = _by_name(tasks, "Task with a compound when clause")
    assert task["when"] == ["some_var is defined", "other_var | bool"]


def test_loop_key_sets_has_loop():
    tasks = inv.scan_role(FIXTURE_ROLE)
    task = _by_name(tasks, "Looped task using loop")
    assert task["has_loop"] is True


def test_legacy_with_items_also_sets_has_loop():
    tasks = inv.scan_role(FIXTURE_ROLE)
    task = _by_name(tasks, "Looped task using legacy with_items")
    assert task["has_loop"] is True


def test_block_and_rescue_are_recursed_into_not_recorded_as_tasks():
    tasks = inv.scan_role(FIXTURE_ROLE)
    names = {t["task_name"] for t in tasks}
    assert "Block wrapping a nested task" not in names
    assert "Task nested inside a block" in names
    assert "Task nested inside a rescue" in names


def test_import_tasks_and_meta_are_excluded_from_the_inventory():
    tasks = inv.scan_role(FIXTURE_ROLE)
    names = {t["task_name"] for t in tasks}
    assert "Pull in another task file" not in names
    assert "Flush handlers early" not in names


def test_include_tasks_is_measurable_unlike_import_tasks():
    # Easy to lump these two together since they sound alike - include_*
    # is dynamic/runtime and DOES fire its own callback event, so it must
    # stay in the inventory, unlike import_tasks.
    tasks = inv.scan_role(FIXTURE_ROLE)
    task = _by_name(tasks, "Dynamically include another task file")
    assert task["action"] == "ansible.builtin.include_tasks"


def test_results_are_sorted_by_file_then_line():
    tasks = inv.scan_role(FIXTURE_ROLE)
    keys = [(t["task_file"] or "", t["task_line"] or 0) for t in tasks]
    assert keys == sorted(keys)


def test_no_tasks_directory_returns_empty_list(tmp_path):
    role_dir = tmp_path / "no_tasks_role"
    role_dir.mkdir()
    assert inv.scan_role(role_dir) == []
