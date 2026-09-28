"""The weekly image-tag check's workflow: once a week, anonymous, read-only.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[4] / ".github/workflows/check-image-tags.yml"


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(WORKFLOW.read_text())
        cls.triggers = cls.workflow[True]  # PyYAML reads the bare key `on` as True
        cls.job = cls.workflow["jobs"]["check-image-tags"]

    def test_it_runs_once_a_week(self):
        (entry,) = self.triggers["schedule"]
        minute, hour, day_of_month, month, day_of_week = entry["cron"].split()
        self.assertEqual((day_of_month, month), ("*", "*"))
        self.assertRegex(day_of_week, r"^[0-6]$")
        self.assertRegex(minute, r"^\d+$")
        self.assertRegex(hour, r"^\d+$")

    def test_the_minute_is_not_the_top_of_the_hour(self):
        self.assertNotEqual(self.triggers["schedule"][0]["cron"].split()[0], "0")

    def test_it_can_also_be_started_by_hand_and_nothing_else_triggers_it(self):
        self.assertEqual(set(self.triggers), {"schedule", "workflow_dispatch"})

    def test_it_needs_no_credentials_and_no_write_access(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        text = WORKFLOW.read_text()
        self.assertNotIn("secrets.", text)
        self.assertNotIn("GITHUB_TOKEN", text)

    def test_a_second_run_never_overlaps_or_cancels_the_first(self):
        self.assertEqual(self.workflow["concurrency"], {"group": "check-image-tags", "cancel-in-progress": False})

    def test_the_run_is_bounded(self):
        self.assertLessEqual(self.job["timeout-minutes"], 15)

    def test_the_only_check_step_runs_the_module_with_plain_python3(self):
        step = next(step for step in self.job["steps"] if "run" in step)
        self.assertEqual(step["run"], "python3 -m ci.images.remote check")
        self.assertEqual(step["working-directory"], "tools")


if __name__ == "__main__":
    unittest.main()
