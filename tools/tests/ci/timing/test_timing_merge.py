"""Tests for ci.timing.merge.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from datetime import date

import pytest
from ci.timing import merge, state

TODAY = date(2026, 11, 15)
ON_DISK = {"a": {"x", "y"}, "b": {"default"}}
CURRENT = {"a": "fa", "b": "fb"}


def recorded(**roles):
    return {"version": 1, "roles": roles}


def old(fingerprint, **seconds):
    return {"fingerprint": fingerprint, "measured": "2026-10-01", "seconds": seconds}


class TestMerge:
    def test_a_role_with_every_scenario_timed_and_passing_is_recorded_on_the_current_fingerprint(self):
        rows = [("a", "x", 10, "passed"), ("a", "y", 20, "passed")]
        merged, problems = merge.merge(recorded(), CURRENT, ON_DISK, rows, TODAY)
        assert merged["roles"] == {"a": {"fingerprint": "fa", "measured": "2026-11-15", "seconds": {"x": 10, "y": 20}}}
        assert problems == []

    def test_the_legs_of_a_split_role_are_combined(self):
        merged, _ = merge.merge(recorded(), CURRENT, ON_DISK, [("a", "y", 20, "passed"), ("a", "x", 10, "passed")], TODAY)
        assert merged["roles"]["a"]["seconds"] == {"x": 10, "y": 20}

    def test_a_role_with_a_failed_scenario_keeps_its_old_entry_and_is_reported(self):
        before = recorded(a=old("older", x=1, y=2))
        merged, problems = merge.merge(before, CURRENT, ON_DISK, [("a", "x", 10, "passed"), ("a", "y", 5, "FAILED")], TODAY)
        assert merged["roles"]["a"] == before["roles"]["a"]
        assert problems == ["a: not recorded (failed: y)"]

    def test_a_role_with_a_scenario_missing_is_not_recorded_and_the_missing_one_is_named(self):
        merged, problems = merge.merge(recorded(), CURRENT, ON_DISK, [("a", "x", 10, "passed")], TODAY)
        assert merged["roles"] == {}
        assert problems == ["a: not recorded (not run: y)"]

    def test_a_scenario_that_failed_before_the_rest_ran_names_both(self):
        _, problems = merge.merge(recorded(), CURRENT, ON_DISK, [("a", "x", 10, "FAILED")], TODAY)
        assert problems == ["a: not recorded (failed: x; not run: y)"]

    def test_a_role_that_was_not_timed_this_run_is_left_as_it_was(self):
        before = recorded(b=old("fb", default=7))
        merged, problems = merge.merge(before, CURRENT, ON_DISK, [("a", "x", 1, "passed"), ("a", "y", 1, "passed")], TODAY)
        assert merged["roles"]["b"] == before["roles"]["b"]
        assert problems == []

    def test_a_role_that_has_no_scenarios_any_more_is_dropped_from_the_state(self):
        before = recorded(gone=old("g", x=1))
        merged, _ = merge.merge(before, CURRENT, ON_DISK, [], TODAY)
        assert merged["roles"] == {}

    def test_timings_for_a_role_the_tree_does_not_have_are_reported_and_not_recorded(self):
        merged, problems = merge.merge(recorded(), CURRENT, ON_DISK, [("ghost", "x", 1, "passed")], TODAY)
        assert merged["roles"] == {}
        assert problems == ["ghost: has no Molecule scenarios in this tree"]

    def test_a_scenario_timed_twice_means_no_row_of_the_role_is_trusted(self):
        rows = [("a", "x", 10, "passed"), ("a", "x", 12, "passed"), ("a", "y", 20, "passed")]
        merged, problems = merge.merge(recorded(), CURRENT, ON_DISK, rows, TODAY)
        assert merged["roles"] == {}
        assert problems == ["a: not recorded (timed more than once: x)"]

    def test_a_role_the_run_was_meant_to_time_that_sent_nothing_is_reported(self):
        merged, problems = merge.merge(recorded(), CURRENT, ON_DISK, [("a", "x", 1, "passed"), ("a", "y", 1, "passed")], TODAY, expected=["a", "b"])
        assert sorted(merged["roles"]) == ["a"]
        assert problems == ["b: no timings received"]

    def test_an_expected_role_the_tree_no_longer_has_is_not_reported_as_missing(self):
        _, problems = merge.merge(recorded(), CURRENT, ON_DISK, [], TODAY, expected=["ghost"])
        assert problems == []

    def test_a_newer_measurement_replaces_the_old_one(self):
        before = recorded(b=old("stale", default=99))
        merged, _ = merge.merge(before, CURRENT, ON_DISK, [("b", "default", 7, "passed")], TODAY)
        assert merged["roles"]["b"]["seconds"] == {"default": 7}
        assert merged["roles"]["b"]["fingerprint"] == "fb"


class TestReadResults:
    def test_every_tsv_file_under_the_directory_is_read_whatever_its_depth(self, root):
        (root / "timings-a-1").mkdir()
        (root / "timings-a-1" / "a.tsv").write_text("a\tx\t1\tpassed\n")
        (root / "b.tsv").write_text("b\tdefault\t2\tpassed\n")
        (root / "notes.txt").write_text("ignored")
        assert sorted(merge.read_results(root)) == [("a", "x", 1, "passed"), ("b", "default", 2, "passed")]

    def test_a_directory_with_no_results_reads_as_none(self, root):
        assert merge.read_results(root) == []

    def test_an_unreadable_row_names_its_file(self, root):
        (root / "bad.tsv").write_text("nonsense\n")
        with pytest.raises(state.ResultError, match=r"bad\.tsv:1"):
            merge.read_results(root)


class TestMain:
    def test_it_records_what_it_can_and_lists_what_it_could_not_in_the_job_summary(self, root, monkeypatch, capsys):
        monkeypatch.setattr(merge.fingerprint, "fingerprints", lambda _root: CURRENT)
        monkeypatch.setattr(merge.molecule_shards, "scenarios_on_disk", lambda _root, role: ON_DISK[role])
        (root / "results").mkdir()
        (root / "results" / "leg.tsv").write_text("a\tx\t1\tpassed\na\ty\t2\tpassed\n")
        summary = root / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        argv = ["--state", str(root / "s.json"), "--results", str(root / "results"), "--out", str(root / "s.json"), "--expect", '["a","b"]']
        assert merge.main(argv) == 0
        assert sorted(state.load(root / "s.json")["roles"]) == ["a"]
        assert "::warning::b: no timings received" in capsys.readouterr().out
        assert "- b: no timings received" in summary.read_text()
