"""Unit tests for doc_reliance.py - which declared reliances are unmet (ADR 0080)."""

from __future__ import annotations

import pytest
from _doc_fixtures import revision
from doc_scripts import check_doc_drift as drift
from doc_scripts import doc_reliance as reliance

RELIES = [{"adr": "ADR-0002", "reason": "It presupposes the proxy boundary."}]


def reliant(root, status):
    return revision(root, "0001-reliant", 0, status=status, relies_on=RELIES)


def target(root, status):
    return revision(root, "0002-target", 0, status=status)


class TestWhatIsUnmet:
    @pytest.mark.parametrize(
        ("reliant_status", "target_status", "unmet"),
        [
            ("approved", "working", True),
            ("approved", "approved", False),
            ("approved", "accepted", False),
            ("accepted", "working", True),
            ("accepted", "approved", True),
            ("accepted", "accepted", False),
        ],
    )
    def test_the_reliant_state_sets_what_the_target_must_be(self, root, reliant_status, target_status, unmet):
        reliant(root, reliant_status)
        target(root, target_status)
        assert bool(reliance.unmet_reliances(root)) is unmet

    @pytest.mark.parametrize("status", ["working", "superseded", "abandoned", "retired"])
    def test_a_reliant_revision_that_claims_nothing_is_not_checked(self, root, status):
        extra = {"superseded_by": 1} if status == "superseded" else {}
        revision(root, "0001-reliant", 0, status=status, relies_on=RELIES, **extra)
        target(root, "working")
        assert reliance.unmet_reliances(root) == []

    def test_any_revision_of_the_target_lineage_can_meet_it(self, root):
        reliant(root, "approved")
        revision(root, "0002-target", 0, status="superseded", superseded_by=1)
        revision(root, "0002-target", 1, status="approved", supersedes=0)
        assert reliance.unmet_reliances(root) == []

    def test_a_reliance_on_an_unknown_lineage_is_left_to_the_lineage_check(self, root):
        reliant(root, "approved")
        assert reliance.unmet_reliances(root) == []

    def test_related_is_never_read_as_reliance(self, root):
        revision(root, "0001-reliant", 0, status="accepted", related=["ADR-0002"])
        target(root, "working")
        assert reliance.unmet_reliances(root) == []


def test_the_warning_names_the_reliant_revision_the_target_its_state_and_the_reason(root):
    reliant(root, "approved")
    target(root, "working")
    (warning,) = reliance.reliance_warnings(root)
    assert "docs/decisions/0001-reliant/revision-000.md" in warning
    assert "approved" in warning
    assert "ADR-0002" in warning
    assert "working" in warning
    assert "It presupposes the proxy boundary." in warning


class TestTheCheckCommand:
    @pytest.fixture(autouse=True)
    def _repo(self, root, monkeypatch):
        monkeypatch.setattr(drift, "ROOT", root)
        monkeypatch.setattr(drift, "errors", [])
        for name in (
            "check_doc_indexes",
            "check_ansible_reference",
            "check_molecule_matrix",
            "check_deploy_flow",
            "check_ci_jobs_table",
            "check_no_stale_anchors",
            "check_doc_path_mentions",
            "check_adr_link_names",
            "check_nist_alignment_currency",
        ):
            monkeypatch.setattr(drift, name, lambda: None)
        for name in ("heading_errors", "open_assumption_errors", "weight_errors", "project_errors", "exploration_errors", "record_errors", "ledger_errors"):
            monkeypatch.setattr(drift, name, lambda root: [])
        reliant(root, "approved")
        target(root, "working")

    def test_an_unmet_reliance_is_printed_and_does_not_change_the_exit_status(self, capsys):
        assert drift.main([]) == 0
        out = capsys.readouterr().out
        assert "::warning::" in out
        assert "ADR-0002" in out

    def test_strict_turns_the_warning_into_a_failure(self, capsys):
        assert drift.main(["--strict"]) == 1
        captured = capsys.readouterr()
        assert "::error::" in captured.out
        assert "1 doc-drift issue(s) found." in captured.err

    def test_strict_is_clean_once_the_target_is_approved(self, root, capsys):
        target(root, "approved")
        assert drift.main(["--strict"]) == 0
        assert "::warning::" not in capsys.readouterr().out
