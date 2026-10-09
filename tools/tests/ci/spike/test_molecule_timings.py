"""Tests for ci.spike.molecule_timings.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json

import pytest
from ci.spike import molecule_timings as mt


def job(name, created, started, completed, steps=(), conclusion="success"):
    day = "2026-10-09T"
    return json.dumps(
        {
            "name": name,
            "created_at": f"{day}{created}Z",
            "started_at": f"{day}{started}Z" if started else None,
            "completed_at": f"{day}{completed}Z" if completed else None,
            "conclusion": conclusion,
            "steps": [{"name": n, "started_at": f"{day}{s}Z", "completed_at": f"{day}{e}Z"} for n, s, e in steps],
        }
    )


class TestParseJobs:
    def test_skipped_unstarted_and_the_spike_job_itself_are_dropped(self):
        lines = [
            job("kept", "10:00:00", "10:00:05", "10:01:00"),
            job("skipped", "10:00:00", "10:00:05", "10:00:05", conclusion="skipped"),
            job("never-started", "10:00:00", None, None, conclusion=None),
            job(mt.SELF, "10:00:00", "10:00:05", "10:01:00"),
            "",
        ]
        assert [j["name"] for j in mt.parse_jobs(lines)] == ["kept"]

    def test_queue_and_run_seconds(self):
        (parsed,) = mt.parse_jobs([job("a", "10:00:00", "10:00:30", "10:02:30")])
        assert (mt.queued(parsed), mt.ran(parsed)) == (30, 120)


class TestConcurrency:
    def test_peak_and_time_at_the_cap(self):
        jobs = mt.parse_jobs(
            [
                job("a", "10:00:00", "10:00:00", "10:01:00"),
                job("b", "10:00:00", "10:00:10", "10:01:10"),
                job("c", "10:00:00", "10:00:20", "10:00:40"),
            ]
        )
        assert mt.concurrency(jobs, cap=3) == (3, 20)
        assert mt.concurrency(jobs, cap=4) == (3, 0)


class TestLegSplit:
    def test_separates_the_scenario_step_from_everything_else(self):
        (leg,) = mt.parse_jobs(
            [
                job(
                    "molecule (x-1)",
                    "10:00:00",
                    "10:00:00",
                    "10:10:00",
                    steps=[("Setup uv", "10:00:00", "10:01:00"), ("Run molecule test — x-1", "10:01:00", "10:09:00"), ("Pack", "10:09:00", "10:10:00")],
                )
            ]
        )
        assert mt.leg_split(leg) == (480, 120)


class TestSplitMakespan:
    @pytest.mark.parametrize(
        ("durations", "shards", "expected"),
        [([60, 50, 40, 30], 2, 90), ([60, 50, 40, 30], 4, 60), ([60], 3, 60), ([], 2, 0)],
    )
    def test_longest_first_into_the_emptiest_bin(self, durations, shards, expected):
        assert mt.split_makespan(durations, shards) == expected


class TestReadTimings:
    def test_the_file_name_gives_the_leg_and_the_rows_give_the_role(self, root):
        (root / "timings-x-1.tsv").write_text("x\ta\t300\tpassed\n")
        (root / "timings-x-2.tsv").write_text("x\tb\t200\tFAILED\n")
        assert mt.read_timings(root) == [("x-1", "x", "a", 300, "passed"), ("x-2", "x", "b", 200, "FAILED")]


def test_render_reports_the_run_each_leg_and_each_role(root):
    (root / "timings-x-1.tsv").write_text("x\ta\t300\tpassed\n")
    (root / "timings-x-2.tsv").write_text("x\tb\t200\tpassed\n")

    def leg(name, scenario_seconds):
        return job(
            f"molecule ({name})",
            "10:00:00",
            "10:00:10",
            f"10:{(scenario_seconds + 70) // 60:02d}:{(scenario_seconds + 70) % 60:02d}",
            steps=[("Setup uv", "10:00:10", "10:01:10"), (f"Run molecule test — {name}", "10:01:10", "10:09:10")],
        )

    jobs = mt.parse_jobs([leg("x-1", 300), leg("x-2", 200)])
    report = mt.render(jobs, mt.read_timings(root), mt.parse_time("2026-10-09T10:00:00Z"))
    assert "| x-1 | 1 |" in report
    assert "| x | 2 | 2 | 8m20s |" in report
    assert "| x-1 | x/a | 300 | passed |" in report
    assert "Wall time from run start to last job:" in report
