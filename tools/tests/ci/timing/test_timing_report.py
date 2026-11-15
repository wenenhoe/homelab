"""Tests for ci.timing.report.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
import yaml
from ci.timing import report

TARGET = 600
GAIN_SECONDS = 30
GAIN_RATIO = 0.1


def recorded(**roles):
    return {"version": 1, "roles": {role: {"fingerprint": "f", "measured": "2026-11-01", "seconds": seconds} for role, seconds in roles.items()}}


def changes(state, table=None):
    return report.changes(state, table or {}, TARGET, GAIN_SECONDS, GAIN_RATIO)


class TestPack:
    def test_the_longest_scenario_goes_first_into_the_least_loaded_shard(self):
        assert report.pack({"a": 100, "b": 90, "c": 60, "d": 50}, 2) == [["a", "d"], ["b", "c"]]

    def test_the_heaviest_shard_comes_first(self):
        shards = report.pack({"big": 500, "s1": 100, "s2": 100, "s3": 100}, 2)
        assert shards[0] == ["big"]
        assert sorted(shards[1]) == ["s1", "s2", "s3"]

    def test_equal_times_are_placed_by_name_so_the_layout_is_stable(self):
        assert report.pack({"c": 10, "a": 10, "b": 10}, 3) == [["a"], ["b"], ["c"]]

    def test_one_shard_holds_everything(self):
        assert report.pack({"x": 1, "y": 2}, 1) == [["y", "x"]]


class TestChanges:
    def test_a_role_within_the_target_and_not_split_is_left_alone(self):
        assert changes(recorded(small={"a": 100, "b": 100})) == []

    def test_an_unsplit_role_past_the_target_is_proposed_in_enough_shards(self):
        (change,) = changes(recorded(slow={"a": 500, "b": 400, "c": 300, "d": 200}))
        assert (change.role, len(change.current), len(change.proposed), change.why) == ("slow", 1, 3, "longest leg is past the target")
        assert (change.current_longest, change.proposed_longest) == (1400, 500)

    def test_the_slowest_scenario_is_reported_as_the_floor_a_split_cannot_pass(self):
        (change,) = changes(recorded(slow={"huge": 1500, "a": 400, "b": 400, "c": 400}))
        assert change.floor == 1500
        assert change.proposed_longest == 1500

    def test_a_role_whose_one_scenario_is_over_the_target_is_not_proposed_when_no_split_helps(self):
        assert changes(recorded(one={"only": 900})) == []

    def test_a_split_that_is_unevenly_loaded_is_repacked_at_the_same_leg_count(self):
        state = recorded(r={"a": 300, "b": 250, "c": 200, "d": 150})
        (change,) = changes(state, {"r": [["a", "b"], ["c", "d"]]})
        assert change.why == "legs are unevenly loaded"
        assert (change.current_longest, change.proposed_longest) == (550, 450)
        assert len(change.proposed) == 2

    def test_a_split_that_is_a_little_uneven_is_left_alone(self):
        assert changes(recorded(r={"a": 300, "b": 290, "c": 280, "d": 270}), {"r": [["a", "d"], ["b", "c"]]}) == []

    def test_a_gain_below_the_seconds_threshold_is_left_alone_even_when_large_in_proportion(self):
        state = recorded(r={"a": 30, "b": 20, "c": 10, "d": 10})
        assert report.changes(state, {"r": [["a", "b"], ["c", "d"]]}, 60, GAIN_SECONDS, GAIN_RATIO) == []

    def test_a_split_role_that_fits_the_target_in_fewer_legs_is_proposed_in_fewer(self):
        (change,) = changes(recorded(r={"a": 100, "b": 100, "c": 100}), {"r": [["a"], ["b"], ["c"]]})
        assert change.why == "fewer legs fit the target"
        assert len(change.proposed) == 1

    def test_a_role_missing_a_scenario_the_table_lists_is_skipped_until_it_is_measured_again(self):
        assert changes(recorded(r={"a": 900, "b": 900}), {"r": [["a"], ["b"], ["c"]]}) == []

    def test_a_role_with_no_timings_is_skipped(self):
        assert changes(recorded(r={})) == []


class TestTableText:
    def test_a_proposal_is_in_the_tables_own_format(self):
        (change,) = changes(recorded(slow={"a": 500, "b": 400, "c": 300, "d": 200}))
        assert yaml.safe_load(report.table_text([change])) == {"slow": [["a"], ["c", "d"], ["b"]]}

    def test_a_role_that_needs_one_leg_becomes_a_comment_since_the_table_lists_only_split_roles(self):
        (change,) = changes(recorded(r={"a": 100, "b": 100}), {"r": [["a"], ["b"]]})
        assert report.table_text([change]) == "# r: one leg, remove it from the table\n"

    def test_no_change_is_no_text(self):
        assert report.table_text([]) == ""


class TestMarkdown:
    def test_with_nothing_to_change_it_says_so_and_counts_what_was_measured(self):
        text = report.markdown(recorded(a={"x": 1}), ["a", "b"], [], TARGET)
        assert "1 of 2 roles measured" in text
        assert "Not measured yet: b." in text
        assert "within the thresholds" in text

    def test_a_change_is_a_row_with_the_legs_and_longest_leg_before_and_after(self):
        (change,) = changes(recorded(slow={"a": 500, "b": 400, "c": 300, "d": 200}))
        text = report.markdown(recorded(slow={"a": 500, "b": 400, "c": 300, "d": 200}), ["slow"], [change], TARGET)
        assert "| slow | 1 | 23m20s | 3 | 8m20s | 8m20s | longest leg is past the target |" in text

    @pytest.mark.parametrize(("seconds", "expected"), [(0, "0m00s"), (65, "1m05s"), (600, "10m00s")])
    def test_minutes_pads_the_seconds(self, seconds, expected):
        assert report.minutes(seconds) == expected


class TestMain:
    def test_it_prints_the_report_and_writes_the_proposal_only_when_something_changes(self, root, monkeypatch, capsys):
        monkeypatch.setattr(report.molecule_shards, "load_table", lambda _root: {})
        monkeypatch.setattr(report.molecule_scope, "role_names", lambda _root: ["slow"])
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        report.state.save(root / "s.json", recorded(slow={"a": 500, "b": 400, "c": 300, "d": 200}))
        assert report.main(["--state", str(root / "s.json"), "--proposal", str(root / "p.yml")]) == 0
        assert "| slow |" in capsys.readouterr().out
        assert yaml.safe_load((root / "p.yml").read_text()) == {"slow": [["a"], ["c", "d"], ["b"]]}

    def test_a_table_that_disagrees_with_the_tree_fails_the_run(self, root, monkeypatch, capsys):
        def broken(_root):
            raise report.molecule_shards.ShardError("x must list at least two shards")

        monkeypatch.setattr(report.molecule_shards, "load_table", broken)
        assert report.main(["--state", str(root / "s.json")]) == 1
        assert "x must list at least two shards" in capsys.readouterr().err
