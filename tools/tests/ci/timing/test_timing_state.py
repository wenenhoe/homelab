"""Tests for ci.timing.state.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json

import pytest
from ci.timing import state


class TestLoad:
    def test_a_file_that_is_not_there_is_an_empty_state(self, root):
        assert state.load(root / "none.json") == state.empty()

    @pytest.mark.parametrize(
        "text",
        ["{not json", "[]", '{"version": 99, "roles": {}}', '{"version": 1, "roles": []}', '{"roles": {}}'],
        ids=["unparsable", "not an object", "other version", "roles not an object", "no version"],
    )
    def test_a_file_that_cannot_be_trusted_is_an_empty_state(self, root, text):
        path = root / "state.json"
        path.write_text(text)
        assert state.load(path) == state.empty()

    def test_a_saved_state_reads_back_the_same_and_creates_its_directory(self, root):
        recorded = {"version": 1, "roles": {"a": {"fingerprint": "f", "measured": "2026-11-01", "seconds": {"x": 3}}}}
        path = root / "nested" / "state.json"
        state.save(path, recorded)
        assert state.load(path) == recorded
        assert json.loads(path.read_text()) == recorded


class TestParseResults:
    def test_each_row_is_role_scenario_seconds_and_result(self):
        assert state.parse_results("a\tx\t12\tpassed\nb\tdefault\t0\tFAILED\n") == [("a", "x", 12, "passed"), ("b", "default", 0, "FAILED")]

    def test_blank_lines_are_ignored(self):
        assert state.parse_results("\na\tx\t1\tpassed\n\n") == [("a", "x", 1, "passed")]

    @pytest.mark.parametrize(
        "line", ["a\tx\t1", "a\tx\tslow\tpassed", "a x 1 passed", "a\tx\t1\tpassed\textra"], ids=["short", "seconds not a number", "no tabs", "long"]
    )
    def test_a_row_of_another_shape_names_its_source_and_line(self, line):
        with pytest.raises(state.ResultError, match=r"leg\.tsv:2: expected role"):
            state.parse_results(f"a\tx\t1\tpassed\n{line}\n", "leg.tsv")
