"""Tests for ci.output.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from ci import output


class TestWriteSummary:
    def test_the_lines_are_appended_as_a_list_under_the_title(self, root, monkeypatch):
        summary = root / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        output.write_summary("Checks", ["a", "b"])
        assert summary.read_text() == "### Checks\n\n- a\n- b\n"

    def test_a_second_write_is_added_after_the_first(self, root, monkeypatch):
        summary = root / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        output.write_summary("One", ["a"])
        output.write_summary("Two", ["b"])
        assert summary.read_text() == "### One\n\n- a\n### Two\n\n- b\n"

    def test_nothing_is_written_outside_actions(self, root, monkeypatch, capsys):
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        output.write_summary("Checks", ["a"])
        assert capsys.readouterr().out == ""
