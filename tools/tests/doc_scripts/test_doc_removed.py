"""Unit tests for doc_removed.py - the ledger of removed decision numbers and the
rule that a lineage with an accepted record leaves only on the record.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from _doc_fixtures import assert_one_error, revision
from doc_scripts import doc_removed as removed

HEADER = "# Removed\n\n| ADR | Fate | Where it went |\n| :--- | :--- | :--- |\n"


def ledger(root, *rows):
    path = root / "docs/decisions/removed.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + "".join(f"{r}\n" for r in rows), encoding="utf-8")


class TestLedger:
    def test_no_ledger_is_clean(self, root):
        assert removed.ledger_errors(root) == []
        assert removed.ledger_numbers(root) == {}

    def test_rows_are_read(self, root):
        ledger(root, "| 0032 | demoted | the tooling topic doc |", "| 0033 | dropped | not needed |")
        assert removed.ledger_numbers(root) == {"0032": ("demoted", "the tooling topic doc"), "0033": ("dropped", "not needed")}
        assert removed.ledger_errors(root) == []

    def test_a_listed_number_cannot_be_a_live_lineage(self, root):
        revision(root, "0032-x", 0)
        ledger(root, "| 0032 | demoted | a doc |")
        assert_one_error(removed.ledger_errors(root), "0032", "never reused")

    def test_a_listed_number_cannot_also_be_a_former_id(self, root):
        revision(root, "0050-merged", 0, former_ids=["ADR-0032"])
        ledger(root, "| 0032 | dropped | gone |")
        assert_one_error(removed.ledger_errors(root), "0032", "former id")

    def test_a_malformed_row_is_reported(self, root):
        ledger(root, "| 0032 | merged | elsewhere |")
        assert_one_error(removed.ledger_errors(root), "0032")

    def test_a_number_listed_twice_is_reported(self, root):
        ledger(root, "| 0032 | demoted | a |", "| 0032 | dropped | b |")
        assert_one_error(removed.ledger_errors(root), "listed twice")


class TestRemovalErrors:
    def test_a_lineage_still_in_the_tree_is_clean(self, root):
        revision(root, "0032-x", 0, status="accepted")
        assert removed.removal_errors({"0032": {"accepted"}}, root) == []

    def test_an_accepted_lineage_that_vanished_unaccounted_is_reported(self, root):
        assert_one_error(removed.removal_errors({"0032": {"accepted"}}, root), "ADR 0032", "removed.md")

    def test_a_superseded_only_lineage_is_also_held(self, root):
        assert len(removed.removal_errors({"0032": {"superseded"}}, root)) == 1

    def test_a_merged_lineage_is_accounted_for_by_a_former_id(self, root):
        revision(root, "0050-merged", 0, former_ids=["ADR-0032"])
        assert removed.removal_errors({"0032": {"accepted"}}, root) == []

    def test_a_demoted_lineage_is_accounted_for_by_the_ledger(self, root):
        ledger(root, "| 0032 | demoted | a doc |")
        assert removed.removal_errors({"0032": {"accepted"}}, root) == []

    def test_a_lineage_that_never_held_a_decision_may_just_go(self, root):
        assert removed.removal_errors({"0032": {"working"}, "0033": {"abandoned", "working"}}, root) == []
