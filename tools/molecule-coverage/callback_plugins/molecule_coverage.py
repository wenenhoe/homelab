# -*- coding: utf-8 -*-
"""Ansible callback plugin: molecule_coverage

Stage 1 of molecule-coverage. Records, as JSON lines, whether each task was
executed or skipped, for later aggregation into a coverage report. Does not
compute or print any coverage itself yet - that's later stages.

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

    def _write_event(self, result, status: str) -> None:
        task = result._task
        location = task.get_path() if task else ""
        task_file, _, task_line = location.rpartition(":")
        event = {
            "scenario": self._scenario,
            "role": self._role,
            "task_name": task.get_name() if task else None,
            "task_file": task_file or None,
            "task_line": int(task_line) if task_line.isdigit() else None,
            "action": getattr(task, "action", None),
            "status": status,
            "host": result._host.get_name() if result._host else None,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self._out_path.parent.mkdir(parents=True, exist_ok=True)
        with self._out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    # --- task-result hooks -------------------------------------------------
    def v2_runner_on_ok(self, result):
        status = "changed" if result.is_changed() else "ok"
        self._write_event(result, status)

    def v2_runner_on_skipped(self, result):
        self._write_event(result, "skipped")

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._write_event(result, "failed")

    def v2_runner_on_unreachable(self, result):
        self._write_event(result, "unreachable")
