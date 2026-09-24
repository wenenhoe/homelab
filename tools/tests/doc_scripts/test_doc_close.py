"""Unit tests for doc_close.py - the rule that deleting a project doc must
not leave its decision revision approved and named by no project.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import doc_close as close
from _doc_fixtures import project, revision

DOC = "docs/projects/closing.md"


def base_with(**fm) -> object:
    """A base_project loader that knows only the doc being deleted."""
    return lambda path: fm if path == DOC else None


class CloseErrorsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def errors(self, deleted=(DOC,), **fm) -> list[str]:
        return close.close_errors(list(deleted), base_with(**fm), self.root)

    def assertOneError(self, errors: list[str], *fragments: str) -> None:
        self.assertEqual(len(errors), 1, errors)
        for fragment in fragments:
            self.assertIn(fragment, errors[0])

    def test_nothing_deleted_is_clean(self):
        self.assertEqual(close.close_errors([], base_with(decision="ADR-0001/0"), self.root), [])

    def test_readme_and_template_are_not_project_docs(self):
        deleted = ["docs/projects/README.md", "docs/projects/TEMPLATE.md", "src/a.py"]
        self.assertEqual(close.close_errors(deleted, lambda _: {"decision": "ADR-0001/0"}, self.root), [])

    def test_an_accepted_revision_lets_the_last_project_close(self):
        revision(self.root, "0001-x", 0, status="accepted")
        self.assertEqual(self.errors(decision="ADR-0001/0"), [])

    def test_the_last_project_naming_an_unaccepted_revision_cannot_close(self):
        for status in ("approved", "working"):
            with self.subTest(revision=status):
                revision(self.root, "0001-x", 0, status=status)
                self.assertOneError(self.errors(decision="ADR-0001/0"), DOC, "ADR-0001/0", f"is {status}", "no remaining project doc names it")

    def test_a_sibling_still_naming_the_revision_lets_a_project_close(self):
        revision(self.root, "0001-x", 0, status="approved")
        for sibling_status in ("not-started", "building"):
            with self.subTest(sibling=sibling_status):
                project(self.root, "sibling", status=sibling_status, decision="ADR-0001/0")
                self.assertEqual(self.errors(decision="ADR-0001/0"), [])

    def test_a_successor_for_the_remainder_counts_as_a_sibling(self):
        revision(self.root, "0001-x", 0, status="approved")
        project(self.root, "remainder", status="not-started", decision="ADR-0001/0")
        self.assertEqual(self.errors(decision="ADR-0001/0"), [])

    def test_also_implements_is_not_naming(self):
        revision(self.root, "0001-x", 0, status="approved")
        project(self.root, "other", also_implements=["ADR-0001/0"])
        self.assertOneError(self.errors(decision="ADR-0001/0"), "no remaining project doc names it")

    def test_a_project_naming_a_different_revision_or_candidate_is_not_a_sibling(self):
        revision(self.root, "0001-x", 0, letter="a", status="approved")
        revision(self.root, "0001-x", 0, letter="b", status="abandoned")
        revision(self.root, "0002-y", 0, status="approved")
        project(self.root, "other-candidate", decision="ADR-0001/0-b")
        project(self.root, "other-lineage", decision="ADR-0002/0")
        self.assertOneError(self.errors(decision="ADR-0001/0-a"), "ADR-0001/0-a")

    def test_a_revision_missing_from_the_result_cannot_be_closed_against(self):
        self.assertOneError(self.errors(decision="ADR-0099/0"), "is absent")

    def test_a_project_with_no_decision_closes_freely(self):
        self.assertEqual(self.errors(), [])

    def test_a_doc_the_base_did_not_have_or_with_a_malformed_decision_is_left_to_the_drift_check(self):
        self.assertEqual(close.close_errors([DOC], lambda _: None, self.root), [])
        self.assertEqual(self.errors(decision=["ADR-0001/0"]), [])
        self.assertEqual(self.errors(decision="not-a-ref"), [])

    def test_each_deleted_project_is_judged_on_its_own_decision_and_reported_in_order(self):
        revision(self.root, "0001-x", 0, status="approved")
        revision(self.root, "0002-y", 0, status="accepted")
        decisions = {"docs/projects/b.md": "ADR-0001/0", "docs/projects/a.md": "ADR-0001/0", "docs/projects/c.md": "ADR-0002/0"}
        errors = close.close_errors(list(decisions), lambda p: {"decision": decisions[p]}, self.root)
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(errors[0].startswith("docs/projects/a.md"), errors)
        self.assertTrue(errors[1].startswith("docs/projects/b.md"), errors)

    def test_two_projects_closing_together_do_not_shelter_each_other(self):
        revision(self.root, "0001-x", 0, status="approved")
        decisions = {"docs/projects/a.md": "ADR-0001/0", "docs/projects/b.md": "ADR-0001/0"}
        errors = close.close_errors(list(decisions), lambda p: {"decision": decisions[p]}, self.root)
        self.assertEqual(len(errors), 2, errors)


if __name__ == "__main__":
    unittest.main()
