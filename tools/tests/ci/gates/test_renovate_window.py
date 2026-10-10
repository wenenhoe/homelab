"""Tests for ci.gates.renovate_window.

Cron parsing and the window rule run on fixed instants; config reading runs
on scratch renovate.json5 text; the last class holds the real config to the
truth table: a miss on Monday and Thursday from 06:00 Singapore, a pass otherwise.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
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


class TestCron:
    def test_fields_of_the_real_schedule(self):
        schedule = rw.Schedule.parse("* 0-5 * * 1,4")
        assert schedule.hours == frozenset(range(6))
        assert schedule.days_of_week == frozenset({1, 4})
        assert not schedule.dom_restricted
        assert schedule.dow_restricted

    def test_lists_ranges_and_steps(self):
        schedule = rw.Schedule.parse("* 1,3-5,20-23/2 * * *")
        assert schedule.hours == frozenset({1, 3, 4, 5, 20, 22})

    def test_star_step_and_open_ended_step(self):
        assert rw.Schedule.parse("* */6 * * *").hours == frozenset({0, 6, 12, 18})
        assert rw.Schedule.parse("* 20/2 * * *").hours == frozenset({20, 22})

    def test_sunday_is_zero_or_seven(self):
        assert rw.Schedule.parse("* * * * 7").days_of_week == frozenset({0})
        assert rw.Schedule.parse("* * * * 0,7").days_of_week == frozenset({0})

    @pytest.mark.parametrize(
        "bad",
        [
            pytest.param("* 0-5 * *", id="four-fields"),
            pytest.param("* 0-5 * * 1 2", id="six-fields"),
            pytest.param("0 0-5 * * 1", id="minute-not-star"),
            pytest.param("* 6-2 * * *", id="reversed-range"),
            pytest.param("* 24 * * *", id="hour-out-of-range"),
            pytest.param("* * 0 * *", id="day-of-month-zero"),
            pytest.param("* * * 13 *", id="month-out-of-range"),
            pytest.param("* * * * 8", id="day-of-week-out-of-range"),
            pytest.param("* mon * * *", id="name-instead-of-number"),
            pytest.param("* */0 * * *", id="zero-step"),
            pytest.param("* a-b * * *", id="non-numeric-range"),
        ],
    )
    def test_malformed_schedules_are_errors(self, bad):
        with pytest.raises(rw.WindowError):
            rw.Schedule.parse(bad)


class TestWindow:
    SCHEDULE = rw.Schedule.parse("* 0-5 * * 1,4")

    def compliant(self, *args: int) -> bool:
        return self.SCHEDULE.compliant(datetime(*args, tzinfo=SGT))

    def test_inside_the_window_on_a_window_day_passes(self):
        # 2026-09-28 is a Monday, 2026-10-01 a Thursday.
        assert self.compliant(2026, 9, 28, 0, 0)
        assert self.compliant(2026, 9, 28, 1, 37)
        assert self.compliant(2026, 9, 28, 5, 59)
        assert self.compliant(2026, 10, 1, 3, 0)

    def test_after_the_window_closes_on_a_window_day_fails(self):
        assert not self.compliant(2026, 9, 28, 6, 0)
        assert not self.compliant(2026, 9, 28, 23, 59)
        assert not self.compliant(2026, 10, 1, 7, 10)

    @pytest.mark.parametrize(
        ("month", "day", "hour"),
        [
            *[pytest.param(9, day, hour, id=f"{name}-{hour:02}") for day, name in ((29, "tuesday"), (30, "wednesday")) for hour in (0, 3, 6, 12, 23)],
            pytest.param(10, 4, 9, id="sunday-09"),
        ],
    )
    def test_a_day_with_no_window_always_passes(self, month, day, hour):
        assert self.compliant(2026, month, day, hour)

    def test_a_run_starting_before_a_later_window_fails(self):
        schedule = rw.Schedule.parse("* 2-5 * * 1")
        assert not schedule.compliant(datetime(2026, 9, 28, 1, 37, tzinfo=SGT))

    def test_day_of_month_and_day_of_week_both_restricted_match_either(self):
        schedule = rw.Schedule.parse("* 0-5 1 * 1")
        assert schedule.has_window_on(datetime(2026, 9, 28, tzinfo=SGT))  # a Monday, not the 1st
        assert schedule.has_window_on(datetime(2026, 10, 1, tzinfo=SGT))  # the 1st, a Thursday
        assert not schedule.has_window_on(datetime(2026, 9, 29, tzinfo=SGT))

    def test_a_restricted_month_excludes_other_months(self):
        schedule = rw.Schedule.parse("* 0-5 * 10 *")
        assert not schedule.has_window_on(datetime(2026, 9, 28, tzinfo=SGT))
        assert schedule.has_window_on(datetime(2026, 10, 5, tzinfo=SGT))


def write(root: Path, text: str) -> None:
    path = root / rw.RENOVATE_CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class TestConfig:
    def test_reads_timezone_and_deduplicated_schedules_ignoring_comments(self, root):
        write(root, CONFIG)
        zone, schedules = rw.load_config(root)
        assert zone == "Asia/Singapore"
        assert [s.expression for s in schedules] == ["* 0-5 * * 1,4"]

    def test_distinct_schedules_are_all_kept(self, root):
        write(root, CONFIG.replace('schedule: ["* 0-5 * * 1,4"],\n  }', 'schedule: ["* 0-5 * * 2"],\n  }'))
        assert [s.expression for s in rw.load_config(root)[1]] == ["* 0-5 * * 1,4", "* 0-5 * * 2"]

    def test_a_multi_entry_schedule_array_is_read(self, root):
        write(root, 'timezone: "UTC",\nschedule: ["* 0-5 * * 1", "* 8 * * 6"],\n')
        assert [s.expression for s in rw.load_config(root)[1]] == ["* 0-5 * * 1", "* 8 * * 6"]

    def test_missing_file_schedule_or_timezone_is_an_error(self, root):
        with pytest.raises(rw.WindowError, match="can't read"):
            rw.load_config(root)
        write(root, 'timezone: "UTC",\n')
        with pytest.raises(rw.WindowError, match="no `schedule:`"):
            rw.load_config(root)
        write(root, 'schedule: ["* 0-5 * * 1"],\n')
        with pytest.raises(rw.WindowError, match="no `timezone:`"):
            rw.load_config(root)

    def test_an_unknown_timezone_is_an_error(self, root):
        write(root, CONFIG.replace("Asia/Singapore", "Mars/Olympus"))
        with pytest.raises(rw.WindowError, match="unknown timezone"):
            rw.check(root, 0)


@pytest.fixture
def configured_root(root):
    path = root / rw.RENOVATE_CONFIG
    path.parent.mkdir(parents=True)
    path.write_text(CONFIG)
    return root


class TestCheck:
    def test_the_schedules_own_cron_tick_lands_after_midnight_singapore_the_next_day(self, configured_root):
        # 17:37 UTC is 01:37 SGT the following calendar day.
        wednesday_utc = epoch(2026, 9, 30, 17, 37, UTC)  # Thursday 01:37 SGT
        assert rw.check(configured_root, wednesday_utc) == []

    def test_the_observed_scheduled_run_lag_still_fits_but_a_longer_one_does_not(self, configured_root):
        tick = epoch(2026, 9, 30, 17, 37, UTC)
        assert rw.check(configured_root, tick + int(2.33 * 3600)) == []  # 2h20m: 03:57 SGT
        (problem,) = rw.check(configured_root, tick + 5 * 3600)  # 06:37 SGT
        assert "Thu 2026-10-01 06:37 (Asia/Singapore)" in problem
        assert "'* 0-5 * * 1,4'" in problem

    def test_a_run_that_missed_two_schedules_reports_both(self, configured_root):
        (configured_root / rw.RENOVATE_CONFIG).write_text(CONFIG.replace('schedule: ["* 0-5 * * 1,4"],\n  }', 'schedule: ["* 0-5 * * 1"],\n  }'))
        problems = rw.check(configured_root, epoch(2026, 9, 28, 9, 0))  # Monday 09:00 SGT
        assert len(problems) == 2

    def test_main_returns_the_verdict(self, configured_root, monkeypatch):
        monkeypatch.setattr(rw, "REPO_ROOT", configured_root)
        assert rw.main([str(epoch(2026, 9, 28, 1, 0))]) == 0
        assert rw.main([str(epoch(2026, 9, 28, 7, 0))]) == 1

    def test_main_reports_a_configuration_error_as_a_failure(self, configured_root, monkeypatch):
        (configured_root / rw.RENOVATE_CONFIG).unlink()
        monkeypatch.setattr(rw, "REPO_ROOT", configured_root)
        assert rw.main(["0"]) == 1


class TestRealConfig:
    def test_the_real_config_parses(self):
        zone, schedules = rw.load_config(rw.REPO_ROOT)
        assert zone == "Asia/Singapore"
        assert schedules

    def test_monday_and_thursday_from_0600_singapore_miss_and_everything_else_passes(self, subtests):
        """Monday or Thursday from 06:00 Singapore is a miss; everything else passes."""
        misses = 0
        start = epoch(2026, 9, 28, 0)
        for half_hours in range(2 * 24 * 14):
            moment = start + half_hours * 1800
            local = datetime.fromtimestamp(moment, SGT)
            expected_miss = local.isoweekday() in (1, 4) and local.hour >= 6
            with subtests.test(at=local.isoformat()):
                assert bool(rw.check(rw.REPO_ROOT, moment)) == expected_miss
            misses += expected_miss
        # Two Mondays and two Thursdays, 06:00-23:59 is 18 hours, checked twice an hour.
        assert misses == 4 * 18 * 2

    def test_the_workflows_cron_tick_is_inside_the_window_with_the_buffer_it_claims(self):
        workflow = (rw.REPO_ROOT / ".github/workflows/renovate.yml").read_text()
        assert 'cron: "37 17 * * *"' in workflow
        tick = epoch(2026, 9, 30, 17, 37, UTC)
        assert rw.check(rw.REPO_ROOT, tick) == []
        assert rw.check(rw.REPO_ROOT, tick + 4 * 3600 + 21 * 60) == []  # 05:58 SGT: the ~4h22m buffer
        assert rw.check(rw.REPO_ROOT, tick + 4 * 3600 + 23 * 60)  # 06:00 SGT

    def test_environment_timezone_does_not_matter(self, monkeypatch):
        monkeypatch.setenv("TZ", "America/Los_Angeles")
        assert rw.check(rw.REPO_ROOT, epoch(2026, 9, 28, 9, 0))
