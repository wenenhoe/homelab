"""Unit tests for doc_close.py - the rule that deleting a project doc must
not leave its decision revision approved and named by no project.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
from _doc_fixtures import assert_one_error, project, revision
from doc_scripts import doc_close as close

DOC = "docs/projects/closing.md"


def base_with(**fm) -> object:
    """A base_project loader that knows only the doc being deleted."""
    return lambda path: fm if path == DOC else None


@pytest.fixture
def errors_for(root):
    def _errors_for(deleted=(DOC,), **fm) -> list[str]:
        return close.close_errors(list(deleted), base_with(**fm), root)

    return _errors_for


class TestCloseErrors:
    def test_nothing_deleted_is_clean(self, root):
        assert close.close_errors([], base_with(decision="ADR-0001/0"), root) == []

    def test_readme_and_template_are_not_project_docs(self, root):
        deleted = ["docs/projects/README.md", "docs/projects/TEMPLATE.md", "src/a.py"]
        assert close.close_errors(deleted, lambda _: {"decision": "ADR-0001/0"}, root) == []

    def test_an_accepted_revision_lets_the_last_project_close(self, root, errors_for):
        revision(root, "0001-x", 0, status="accepted")
        assert errors_for(decision="ADR-0001/0") == []

    @pytest.mark.parametrize("status", ["approved", "working"])
    def test_the_last_project_naming_an_unaccepted_revision_cannot_close(self, root, errors_for, status):
        revision(root, "0001-x", 0, status=status)
        assert_one_error(errors_for(decision="ADR-0001/0"), DOC, "ADR-0001/0", f"is {status}", "no remaining project doc names it")

    @pytest.mark.parametrize("sibling_status", ["not-started", "building"])
    def test_a_sibling_still_naming_the_revision_lets_a_project_close(self, root, errors_for, sibling_status):
        revision(root, "0001-x", 0, status="approved")
        project(root, "sibling", status=sibling_status, decision="ADR-0001/0")
        assert errors_for(decision="ADR-0001/0") == []

    def test_a_successor_for_the_remainder_counts_as_a_sibling(self, root, errors_for):
        revision(root, "0001-x", 0, status="approved")
        project(root, "remainder", status="not-started", decision="ADR-0001/0")
        assert errors_for(decision="ADR-0001/0") == []

    def test_also_implements_is_not_naming(self, root, errors_for):
        revision(root, "0001-x", 0, status="approved")
        project(root, "other", also_implements=["ADR-0001/0"])
        assert_one_error(errors_for(decision="ADR-0001/0"), "no remaining project doc names it")

    def test_a_project_naming_a_different_revision_or_candidate_is_not_a_sibling(self, root, errors_for):
        revision(root, "0001-x", 0, letter="a", status="approved")
        revision(root, "0001-x", 0, letter="b", status="abandoned")
        revision(root, "0002-y", 0, status="approved")
        project(root, "other-candidate", decision="ADR-0001/0-b")
        project(root, "other-lineage", decision="ADR-0002/0")
        assert_one_error(errors_for(decision="ADR-0001/0-a"), "ADR-0001/0-a")

    def test_a_revision_missing_from_the_result_cannot_be_closed_against(self, errors_for):
        assert_one_error(errors_for(decision="ADR-0099/0"), "is absent")

    def test_a_project_with_no_decision_closes_freely(self, errors_for):
        assert errors_for() == []

    def test_a_doc_the_base_did_not_have_or_with_a_malformed_decision_is_left_to_the_drift_check(self, root, errors_for):
        assert close.close_errors([DOC], lambda _: None, root) == []
        assert errors_for(decision=["ADR-0001/0"]) == []
        assert errors_for(decision="not-a-ref") == []

    def test_each_deleted_project_is_judged_on_its_own_decision_and_reported_in_order(self, root):
        revision(root, "0001-x", 0, status="approved")
        revision(root, "0002-y", 0, status="accepted")
        decisions = {"docs/projects/b.md": "ADR-0001/0", "docs/projects/a.md": "ADR-0001/0", "docs/projects/c.md": "ADR-0002/0"}
        errors = close.close_errors(list(decisions), lambda p: {"decision": decisions[p]}, root)
        assert len(errors) == 2, errors
        assert errors[0].startswith("docs/projects/a.md"), errors
        assert errors[1].startswith("docs/projects/b.md"), errors

    def test_two_projects_closing_together_do_not_shelter_each_other(self, root):
        revision(root, "0001-x", 0, status="approved")
        decisions = {"docs/projects/a.md": "ADR-0001/0", "docs/projects/b.md": "ADR-0001/0"}
        errors = close.close_errors(list(decisions), lambda p: {"decision": decisions[p]}, root)
        assert len(errors) == 2, errors
