"""Tests for ci.gates.renovate_window.

Cron parsing and the window rule run on fixed instants; config reading runs
on scratch renovate.json5 text; the last class holds the real config to the
truth table the workflow's old inline shell check implemented.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.gates import renovate_window as rw

SGT = ZoneInfo("Asia/Singapore")
CONFIG = """{
  timezone: "Asia/Singapore",
  // schedule: ["* 9 * * *"] is a comment, not the schedule
  schedule: ["* 0-5 * * 1,4"],
  lockFileMaintenance: {
    enabled: true,
    schedule: ["* 0-5 * * 1,4"],
  },
}
"""


def epoch(year: int, month: int, day: int, hour: int, minute: int = 0, tz: object = SGT) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=tz).timestamp())


class CronTests(unittest.TestCase):
    def test_fields_of_the_real_schedule(self):
        schedule = rw.Schedule.parse("* 0-5 * * 1,4")
        self.assertEqual(schedule.hours, frozenset(range(6)))
        self.assertEqual(schedule.days_of_week, frozenset({1, 4}))
        self.assertFalse(schedule.dom_restricted)
        self.assertTrue(schedule.dow_restricted)

    def test_lists_ranges_and_steps(self):
        schedule = rw.Schedule.parse("* 1,3-5,20-23/2 * * *")
        self.assertEqual(schedule.hours, frozenset({1, 3, 4, 5, 20, 22}))

    def test_star_step_and_open_ended_step(self):
        self.assertEqual(rw.Schedule.parse("* */6 * * *").hours, frozenset({0, 6, 12, 18}))
        self.assertEqual(rw.Schedule.parse("* 20/2 * * *").hours, frozenset({20, 22}))

    def test_sunday_is_zero_or_seven(self):
        self.assertEqual(rw.Schedule.parse("* * * * 7").days_of_week, frozenset({0}))
        self.assertEqual(rw.Schedule.parse("* * * * 0,7").days_of_week, frozenset({0}))

    def test_malformed_schedules_are_errors(self):
        for bad in (
            "* 0-5 * *",
            "* 0-5 * * 1 2",
            "0 0-5 * * 1",
            "* 6-2 * * *",
            "* 24 * * *",
            "* * 0 * *",
            "* * * 13 *",
            "* * * * 8",
            "* mon * * *",
            "* */0 * * *",
            "* a-b * * *",
        ):
            with self.subTest(schedule=bad), self.assertRaises(rw.WindowError):
                rw.Schedule.parse(bad)


class WindowTests(unittest.TestCase):
    SCHEDULE = rw.Schedule.parse("* 0-5 * * 1,4")

    def compliant(self, *args: int) -> bool:
        return self.SCHEDULE.compliant(datetime(*args, tzinfo=SGT))

    def test_inside_the_window_on_a_window_day_passes(self):
        # 2026-09-28 is a Monday, 2026-10-01 a Thursday.
        self.assertTrue(self.compliant(2026, 9, 28, 0, 0))
        self.assertTrue(self.compliant(2026, 9, 28, 1, 37))
        self.assertTrue(self.compliant(2026, 9, 28, 5, 59))
        self.assertTrue(self.compliant(2026, 10, 1, 3, 0))

    def test_after_the_window_closes_on_a_window_day_fails(self):
        self.assertFalse(self.compliant(2026, 9, 28, 6, 0))
        self.assertFalse(self.compliant(2026, 9, 28, 23, 59))
        self.assertFalse(self.compliant(2026, 10, 1, 7, 10))

    def test_a_day_with_no_window_always_passes(self):
        for day in (29, 30):  # Tuesday, Wednesday
            for hour in (0, 3, 6, 12, 23):
                with self.subTest(day=day, hour=hour):
                    self.assertTrue(self.compliant(2026, 9, day, hour))
        self.assertTrue(self.compliant(2026, 10, 4, 9))  # Sunday

    def test_a_run_starting_before_a_later_window_fails(self):
        schedule = rw.Schedule.parse("* 2-5 * * 1")
        self.assertFalse(schedule.compliant(datetime(2026, 9, 28, 1, 37, tzinfo=SGT)))

    def test_day_of_month_and_day_of_week_both_restricted_match_either(self):
        schedule = rw.Schedule.parse("* 0-5 1 * 1")
        self.assertTrue(schedule.has_window_on(datetime(2026, 9, 28, tzinfo=SGT)))  # a Monday, not the 1st
        self.assertTrue(schedule.has_window_on(datetime(2026, 10, 1, tzinfo=SGT)))  # the 1st, a Thursday
        self.assertFalse(schedule.has_window_on(datetime(2026, 9, 29, tzinfo=SGT)))

    def test_a_restricted_month_excludes_other_months(self):
        schedule = rw.Schedule.parse("* 0-5 * 10 *")
        self.assertFalse(schedule.has_window_on(datetime(2026, 9, 28, tzinfo=SGT)))
        self.assertTrue(schedule.has_window_on(datetime(2026, 10, 5, tzinfo=SGT)))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, text: str) -> None:
        path = self.root / rw.RENOVATE_CONFIG
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_reads_timezone_and_deduplicated_schedules_ignoring_comments(self):
        self.write(CONFIG)
        zone, schedules = rw.load_config(self.root)
        self.assertEqual(zone, "Asia/Singapore")
        self.assertEqual([s.expression for s in schedules], ["* 0-5 * * 1,4"])

    def test_distinct_schedules_are_all_kept(self):
        self.write(CONFIG.replace('schedule: ["* 0-5 * * 1,4"],\n  }', 'schedule: ["* 0-5 * * 2"],\n  }'))
        self.assertEqual([s.expression for s in rw.load_config(self.root)[1]], ["* 0-5 * * 1,4", "* 0-5 * * 2"])

    def test_a_multi_entry_schedule_array_is_read(self):
        self.write('timezone: "UTC",\nschedule: ["* 0-5 * * 1", "* 8 * * 6"],\n')
        self.assertEqual([s.expression for s in rw.load_config(self.root)[1]], ["* 0-5 * * 1", "* 8 * * 6"])

    def test_missing_file_schedule_or_timezone_is_an_error(self):
        with self.assertRaisesRegex(rw.WindowError, "can't read"):
            rw.load_config(self.root)
        self.write('timezone: "UTC",\n')
        with self.assertRaisesRegex(rw.WindowError, "no `schedule:`"):
            rw.load_config(self.root)
        self.write('schedule: ["* 0-5 * * 1"],\n')
        with self.assertRaisesRegex(rw.WindowError, "no `timezone:`"):
            rw.load_config(self.root)

    def test_an_unknown_timezone_is_an_error(self):
        self.write(CONFIG.replace("Asia/Singapore", "Mars/Olympus"))
        with self.assertRaisesRegex(rw.WindowError, "unknown timezone"):
            rw.check(self.root, 0)


class CheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        path = self.root / rw.RENOVATE_CONFIG
        path.parent.mkdir(parents=True)
        path.write_text(CONFIG)

    def test_the_schedules_own_cron_tick_lands_after_midnight_singapore_the_next_day(self):
        # 17:37 UTC is 01:37 SGT the following calendar day.
        wednesday_utc = epoch(2026, 9, 30, 17, 37, UTC)  # Thursday 01:37 SGT
        self.assertEqual(rw.check(self.root, wednesday_utc), [])

    def test_the_observed_scheduled_run_lag_still_fits_but_a_longer_one_does_not(self):
        tick = epoch(2026, 9, 30, 17, 37, UTC)
        self.assertEqual(rw.check(self.root, tick + int(2.33 * 3600)), [])  # 2h20m: 03:57 SGT
        (problem,) = rw.check(self.root, tick + 5 * 3600)  # 06:37 SGT
        self.assertIn("Thu 2026-10-01 06:37 (Asia/Singapore)", problem)
        self.assertIn("'* 0-5 * * 1,4'", problem)

    def test_a_run_that_missed_two_schedules_reports_both(self):
        (self.root / rw.RENOVATE_CONFIG).write_text(CONFIG.replace('schedule: ["* 0-5 * * 1,4"],\n  }', 'schedule: ["* 0-5 * * 1"],\n  }'))
        problems = rw.check(self.root, epoch(2026, 9, 28, 9, 0))  # Monday 09:00 SGT
        self.assertEqual(len(problems), 2)

    def test_main_returns_the_verdict(self):
        with patch.object(rw, "REPO_ROOT", self.root):
            self.assertEqual(rw.main([str(epoch(2026, 9, 28, 1, 0))]), 0)
            self.assertEqual(rw.main([str(epoch(2026, 9, 28, 7, 0))]), 1)

    def test_main_reports_a_configuration_error_as_a_failure(self):
        (self.root / rw.RENOVATE_CONFIG).unlink()
        with patch.object(rw, "REPO_ROOT", self.root):
            self.assertEqual(rw.main(["0"]), 1)


class RealConfigTests(unittest.TestCase):
    def test_the_real_config_parses(self):
        zone, schedules = rw.load_config(rw.REPO_ROOT)
        self.assertEqual(zone, "Asia/Singapore")
        self.assertTrue(schedules)

    def test_the_truth_table_the_inline_shell_check_implemented(self):
        """Monday or Thursday from 06:00 Singapore is a miss; everything else passes."""
        misses = 0
        start = epoch(2026, 9, 28, 0)
        for half_hours in range(2 * 24 * 14):
            moment = start + half_hours * 1800
            local = datetime.fromtimestamp(moment, SGT)
            expected_miss = local.isoweekday() in (1, 4) and local.hour >= 6
            with self.subTest(at=local.isoformat()):
                self.assertEqual(bool(rw.check(rw.REPO_ROOT, moment)), expected_miss)
            misses += expected_miss
        # Two Mondays and two Thursdays, 06:00-23:59 is 18 hours, checked twice an hour.
        self.assertEqual(misses, 4 * 18 * 2)

    def test_the_workflows_cron_tick_is_inside_the_window_with_the_buffer_it_claims(self):
        workflow = (rw.REPO_ROOT / ".github/workflows/renovate.yml").read_text()
        self.assertIn('cron: "37 17 * * *"', workflow)
        tick = epoch(2026, 9, 30, 17, 37, UTC)
        self.assertEqual(rw.check(rw.REPO_ROOT, tick), [])
        self.assertEqual(rw.check(rw.REPO_ROOT, tick + 4 * 3600 + 21 * 60), [])  # 05:58 SGT: the ~4h22m buffer
        self.assertTrue(rw.check(rw.REPO_ROOT, tick + 4 * 3600 + 23 * 60))  # 06:00 SGT

    def test_environment_timezone_does_not_matter(self):
        with patch.dict(os.environ, {"TZ": "America/Los_Angeles"}):
            self.assertTrue(rw.check(rw.REPO_ROOT, epoch(2026, 9, 28, 9, 0)))


if __name__ == "__main__":
    unittest.main()
