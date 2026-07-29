# -*- coding: utf-8 -*-
"""Ansible callback plugin: molecule_coverage

Records, as JSON lines, whether each task (and, for looped tasks, each
individual item) was executed or skipped, for later aggregation into a
coverage report. Does not compute or print any coverage itself - that's
inventory.py/aggregate.py/report.py.

Disabled by default; enable per-run via:

    ANSIBLE_CALLBACKS_ENABLED=molecule_coverage

See ../README.md for usage.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

from ansible.plugins.callback import CallbackBase

DOCUMENTATION = r"""
    name: molecule_coverage
    type: notification
    short_description: Record task execution/skip events for coverage reporting
    description:
      - Writes one JSON line per task result (executed or skipped) to a
        per-role, per-scenario JSONL file, for later aggregation by
        molecule-coverage's reporting stage.
    options:
      coverage_dir:
        description: Directory under which <role>/<scenario>.jsonl files are written.
        env:
          - name: MOLECULE_COVERAGE_DIR
        default: ./.molecule-coverage-data
        type: str
      role:
        description: Role name to attribute events to. Falls back to Molecule's own env var, then "unknown".
        env:
          - name: MOLECULE_COVERAGE_ROLE
        type: str
      scenario:
        description: Scenario name to attribute events to. Falls back to Molecule's own env var, then "unknown".
        env:
          - name: MOLECULE_COVERAGE_SCENARIO
        type: str
    requirements:
      - enabled in ansible.cfg or via ANSIBLE_CALLBACKS_ENABLED
"""

# Sentinel distinguishing "no item" (task-level event) from "item is
# genuinely None/falsy" (a real loop item whose value happens to be None,
# 0, "", etc.) - a plain `item=None` default wouldn't be able to tell
# those apart.
_NO_ITEM = object()


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "notification"
    CALLBACK_NAME = "molecule_coverage"
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self):
        super().__init__()
        self._coverage_dir = Path(
            os.environ.get("MOLECULE_COVERAGE_DIR", "./.molecule-coverage-data")
        )
        self._role = (
            os.environ.get("MOLECULE_COVERAGE_ROLE")
            or self._role_from_molecule_env()
            or "unknown"
        )
        self._scenario = (
            os.environ.get("MOLECULE_COVERAGE_SCENARIO")
            or os.environ.get("MOLECULE_SCENARIO_NAME")
            or "unknown"
        )
        self._out_path = self._coverage_dir / self._role / f"{self._scenario}.jsonl"

    @staticmethod
    def _role_from_molecule_env() -> str | None:
        # Molecule sets MOLECULE_PROJECT_DIRECTORY to the role's own root
        # directory (the parent of its molecule/ dir) for role scenarios.
        project_dir = os.environ.get("MOLECULE_PROJECT_DIRECTORY")
        if not project_dir:
            return None
        return Path(project_dir).name

    @staticmethod
    def _json_safe_item(item):
        # Loop items can be arbitrary Jinja2-resolved values (dicts, custom
        # objects, AnsibleUnsafeText, etc.) - not all of which are directly
        # JSON-serializable. Best effort: try as-is first (covers the
        # common str/int/float/bool/list/dict cases), fall back to str().
        try:
            json.dumps(item)
            return item
        except TypeError:
            return str(item)

    def _write_event(
        self, result, status: str, is_item: bool = False, item=_NO_ITEM
    ) -> None:
        task = result._task
        location = task.get_path() if task else ""
        task_file, _, task_line = location.rpartition(":")
        r = result._result if hasattr(result, "_result") else {}
        if is_item and item is _NO_ITEM:
            # no_log: true redacts the ENTIRE result dict Ansible hands to
            # the callback - including "item" - for BOTH the per-item hook
            # AND the task-level aggregate one. Verified empirically: a
            # no_log'd looped task fires item_on_ok/skipped normally, but
            # result._result.get("item") comes back None on every single
            # call, indistinguishable by value alone from a task with no
            # loop at all. is_item is therefore set explicitly by the
            # caller (which hook fired), never inferred from the item
            # value - this branch only fires for a genuinely redacted
            # item, and is recorded as such rather than as "no item".
            item_value = "<redacted by no_log>"
        elif item is _NO_ITEM:
            item_value = None
        else:
            item_value = self._json_safe_item(item)
        event = {
            "scenario": self._scenario,
            "role": self._role,
            "task_name": task.get_name() if task else None,
            "task_file": task_file or None,
            "task_line": int(task_line) if task_line.isdigit() else None,
            "action": getattr(task, "action", None),
            "status": status,
            "host": result._host.get_name() if result._host else None,
            # True only for events from the per-item hooks below - NOT
            # inferred from whether "item" ended up non-null, since
            # no_log can legitimately redact a real item's value.
            "is_item": is_item,
            # None for non-loop task-level events; the item's value (or
            # the no_log placeholder above) for item-level ones.
            "item": item_value,
            # e.g. "Conditional result was False" (when: false) or
            # "No items in the list" (empty loop) - lets later stages tell
            # those two apart, which look identical as a bare "skipped"
            # status. None when Ansible didn't set one (e.g. ok/changed).
            "skip_reason": r.get("skip_reason"),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self._out_path.parent.mkdir(parents=True, exist_ok=True)
        with self._out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    # --- task-result hooks -------------------------------------------------
    # These fire once per task per host, regardless of whether it has a
    # loop - for a looped task, this is the AGGREGATE result (ok/changed if
    # any item succeeded, even if others were skipped/failed - see
    # v2_runner_item_on_* below for the per-item breakdown that catches
    # exactly that blind spot).
    def v2_runner_on_ok(self, result):
        status = "changed" if result.is_changed() else "ok"
        self._write_event(result, status)

    def v2_runner_on_skipped(self, result):
        self._write_event(result, "skipped")

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._write_event(result, "failed")

    def v2_runner_on_unreachable(self, result):
        self._write_event(result, "unreachable")

    # --- per-item hooks (looped tasks only) --------------------------------
    # Fire once per loop iteration, IN ADDITION to the aggregate
    # v2_runner_on_* call above - verified empirically: a loop with items
    # [a, b] where only "a" satisfies the task's when: fires
    # item_on_ok(a), item_on_skipped(b), AND THEN v2_runner_on_ok for the
    # task overall (since at least one item succeeded) - so without these
    # hooks, task-level status alone would report "covered" while silently
    # hiding that item "b" never ran. An empty loop (loop: []) fires NEITHER
    # of these - only the task-level v2_runner_on_skipped, with
    # skip_reason "No items in the list".
    def v2_runner_item_on_ok(self, result):
        status = "changed" if result.is_changed() else "ok"
        self._write_event(result, status, is_item=True, item=result._result.get("item", _NO_ITEM))

    def v2_runner_item_on_skipped(self, result):
        self._write_event(result, "skipped", is_item=True, item=result._result.get("item", _NO_ITEM))

    def v2_runner_item_on_failed(self, result):
        self._write_event(result, "failed", is_item=True, item=result._result.get("item", _NO_ITEM))
