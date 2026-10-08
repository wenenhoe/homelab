"""Unit tests for doc_graph.py - the cross-document lineage, project,
dependency, and decision-gate rules. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
from _doc_fixtures import assert_one_error, project, revision
from doc_scripts import doc_graph as graph


class TestHasOpenAssumptions:
    def test_bullets_under_the_heading_are_open(self):
        assert graph.has_open_assumptions("## Assumptions\n\n- **Claim:** x\n\n## Consequences\n")

    def test_no_heading_or_no_bullets_is_resolved(self):
        assert not graph.has_open_assumptions("## Context\n\ntext\n")
        assert not graph.has_open_assumptions("## Assumptions\n\nAll resolved.\n\n## Consequences\n- a bullet elsewhere\n")

    def test_section_at_end_of_file(self):
        assert graph.has_open_assumptions("## Assumptions\n\n- open\n")


class TestLineageErrors:
    def test_clean_multi_revision_lineage(self, root):
        revision(root, "0013-secret-storage", 0, status="superseded", superseded_by=1)
        revision(root, "0013-secret-storage", 1, status="accepted", supersedes=0)
        revision(root, "0013-secret-storage", 2, status="working")
        assert graph.lineage_errors(root) == []

    def test_no_lineages_is_clean(self, root):
        assert graph.lineage_errors(root) == []

    def test_revision_numbers_start_at_zero_and_have_no_gaps(self, root):
        revision(root, "0001-a", 1)  # a lineage that starts at 001 has no original
        assert_one_error(graph.lineage_errors(root), "000..NNN")
        revision(root, "0002-b", 0)
        revision(root, "0002-b", 2)
        assert any("0002-b" in e and "no gaps" in e for e in graph.lineage_errors(root))

    def test_competing_candidates_are_lettered_from_a_with_none_missing(self, root):
        revision(root, "0001-a", 0, letter="a")
        revision(root, "0001-a", 0, letter="b")
        assert graph.lineage_errors(root) == []
        revision(root, "0002-b", 0, letter="a")
        revision(root, "0002-b", 0, letter="c")
        assert_one_error(graph.lineage_errors(root), "none missing")

    def test_a_competing_generation_cannot_mix_lettered_and_unlettered(self, root):
        revision(root, "0001-a", 0)
        revision(root, "0001-a", 0, letter="b")
        assert_one_error(graph.lineage_errors(root), "competing candidates")

    def test_a_lone_candidate_may_be_unlettered_or_a_but_not_b(self, root):
        revision(root, "0001-a", 0, letter="a")
        revision(root, "0002-b", 0)
        assert graph.lineage_errors(root) == []
        revision(root, "0003-c", 0, letter="b")
        assert_one_error(graph.lineage_errors(root), "only candidate")

    def test_generations_not_files_must_be_contiguous(self, root):
        revision(root, "0001-a", 0, letter="a", status="abandoned")
        revision(root, "0001-a", 0, letter="b", status="working")
        revision(root, "0001-a", 1, status="working")
        assert graph.lineage_errors(root) == []
        revision(root, "0002-b", 0, letter="a", status="abandoned")
        revision(root, "0002-b", 0, letter="b", status="working")
        revision(root, "0002-b", 2, status="working")
        assert any("0002-b" in e and "no gaps" in e for e in graph.lineage_errors(root))

    @pytest.mark.parametrize("chosen", ["approved", "accepted"])
    def test_choosing_one_candidate_requires_abandoning_the_others(self, root, chosen):
        revision(root, "0001-a", 0, letter="a", status=chosen)
        revision(root, "0001-a", 0, letter="b", status="working")
        assert_one_error(graph.lineage_errors(root), "competes with 0-a, which is decided")
        revision(root, "0001-a", 0, letter="b", status="abandoned")  # overwrites the same file
        assert graph.lineage_errors(root) == []

    def test_two_approved_candidates_are_never_valid(self, root):
        revision(root, "0001-a", 0, letter="a", status="approved")
        revision(root, "0001-a", 0, letter="b", status="approved")
        assert any("more than one decided" in e for e in graph.lineage_errors(root))

    def test_working_candidates_may_all_stay_open(self, root):
        revision(root, "0001-a", 0, letter="a", status="working")
        revision(root, "0001-a", 0, letter="b", status="working")
        revision(root, "0001-a", 0, letter="c", status="abandoned")
        assert graph.lineage_errors(root) == []

    def test_only_one_candidate_per_generation_may_be_decided(self, root):
        revision(root, "0001-a", 0, letter="a", status="retired")
        revision(root, "0001-a", 0, letter="b", status="retired")
        assert any("more than one decided" in e for e in graph.lineage_errors(root))

    def test_supersession_names_the_winning_candidate(self, root):
        revision(root, "0001-a", 0, letter="a", status="superseded", superseded_by=1)
        revision(root, "0001-a", 0, letter="b", status="abandoned")
        revision(root, "0001-a", 1, status="accepted", supersedes="0-a")
        assert graph.lineage_errors(root) == []

    def test_successor_must_name_the_candidate_that_was_superseded(self, root):
        revision(root, "0001-a", 0, letter="a", status="superseded", superseded_by=1)
        revision(root, "0001-a", 0, letter="b", status="abandoned")
        revision(root, "0001-a", 1, status="accepted", supersedes="0-b")
        assert any("must declare 'supersedes: 0-a'" in e for e in graph.lineage_errors(root))

    def test_revision_zero_is_a_valid_original_and_first_supersession_target(self, root):
        revision(root, "0001-a", 0, status="superseded", superseded_by=1)
        revision(root, "0001-a", 1, status="accepted", supersedes=0)
        assert graph.lineage_errors(root) == []

    def test_only_one_accepted_revision(self, root):
        revision(root, "0001-a", 0, status="accepted")
        revision(root, "0001-a", 1, status="accepted")
        assert_one_error(graph.lineage_errors(root), "only one may be")

    def test_duplicate_lineage_number(self, root):
        revision(root, "0001-a", 0)
        revision(root, "0001-b", 0)
        assert any("also used by" in e for e in graph.lineage_errors(root))

    def test_title_and_topic_are_stable_across_revisions(self, root):
        revision(root, "0001-a", 0, status="abandoned")
        revision(root, "0001-a", 1, title="A different problem", topic="backup-recovery")
        errors = graph.lineage_errors(root)
        assert len(errors) == 2, errors

    def test_short_name_is_stable_across_revisions(self, root):
        revision(root, "0001-a", 0, status="abandoned")
        revision(root, "0001-a", 1, short="Another name")
        assert_one_error(graph.lineage_errors(root), "'short' differs across revisions")

    def test_short_name_is_unique_across_lineages_ignoring_case(self, root):
        revision(root, "0001-a", 0, short="Secret storage")
        revision(root, "0002-b", 0, short="secret STORAGE")
        assert_one_error(graph.lineage_errors(root), "short name 'secret STORAGE' is already used by ADR-0001")

    def test_superseded_needs_an_accepted_successor(self, root):
        revision(root, "0001-a", 0, status="superseded", superseded_by=1)
        revision(root, "0001-a", 1, status="working", supersedes=0)
        assert_one_error(graph.lineage_errors(root), "only superseded once its successor is accepted")

    def test_superseded_by_must_point_forward_and_exist(self, root):
        revision(root, "0001-a", 0, status="superseded", superseded_by=4)
        assert_one_error(graph.lineage_errors(root), "isn't a later revision")

    def test_successor_must_declare_supersedes(self, root):
        revision(root, "0001-a", 0, status="superseded", superseded_by=1)
        revision(root, "0001-a", 1, status="accepted")
        assert_one_error(graph.lineage_errors(root), "must declare 'supersedes: 0'")

    def test_accepted_successor_requires_the_target_to_be_superseded(self, root):
        revision(root, "0001-a", 0, status="accepted")
        revision(root, "0001-a", 1, status="accepted", supersedes=0)
        errors = graph.lineage_errors(root)
        assert any("must be status: superseded" in e for e in errors), errors

    def test_working_successor_leaves_the_accepted_revision_alone(self, root):
        revision(root, "0001-a", 0, status="accepted")
        revision(root, "0001-a", 1, status="working", supersedes=0)
        assert graph.lineage_errors(root) == []

    def test_supersedes_must_point_backward(self, root):
        revision(root, "0001-a", 0, status="working", supersedes=1)
        revision(root, "0001-a", 1, status="working")
        assert_one_error(graph.lineage_errors(root), "isn't an earlier revision")

    def test_cross_lineage_references_must_resolve(self, root):
        revision(root, "0001-a", 0, narrows="ADR-0009", related=["ADR-0008"])
        errors = graph.lineage_errors(root)
        assert len(errors) == 2, errors
        revision(root, "0002-b", 0, narrows="ADR-0002")
        assert any("narrows its own lineage" in e for e in graph.lineage_errors(root))

    def test_narrows_and_related_between_real_lineages_are_clean(self, root):
        revision(root, "0015-expiry", 0, status="accepted")
        revision(root, "0016-oci", 0, status="accepted", narrows="ADR-0015", related=["ADR-0015"])
        assert graph.lineage_errors(root) == []

    def test_former_id_must_not_be_a_live_lineage(self, root):
        revision(root, "0013-a", 0, status="accepted", former_ids=["ADR-0027"])
        assert graph.lineage_errors(root) == []
        revision(root, "0027-b", 0)
        assert_one_error(graph.lineage_errors(root), "still a live lineage")

    def test_former_id_claimed_twice(self, root):
        revision(root, "0001-a", 0, former_ids=["ADR-0050"])
        revision(root, "0002-b", 0, former_ids=["ADR-0050"])
        assert_one_error(graph.lineage_errors(root), "already claimed")


OPEN_ASSUMPTIONS = "## Assumptions\n\n- **Claim:** it works\n"


class TestOpenAssumptionErrors:
    def test_approved_and_accepted_cannot_carry_open_assumptions(self, root):
        for status in ("approved", "accepted"):
            revision(root, f"000{1 if status == 'approved' else 2}-x", 0, status=status, body=OPEN_ASSUMPTIONS)
        errors = graph.open_assumption_errors(root)
        assert len(errors) == 2, errors

    def test_working_may_carry_them_and_resolved_docs_pass(self, root):
        revision(root, "0001-x", 0, status="working", body=OPEN_ASSUMPTIONS)
        revision(root, "0002-y", 0, status="accepted", body="## Context\n\nfacts\n")
        assert graph.open_assumption_errors(root) == []


DECISION_GATE_ALLOWED = {
    "not-started": {"working", "approved"},
    "de-risking": {"working"},
    "building": {"approved"},
    "done": {"accepted"},
}
DECISION_GATE_REVISION_STATUSES = ["working", "approved", "accepted", "abandoned", "retired"]


class TestProjectErrors:
    def test_no_projects_is_clean(self, root):
        assert graph.project_errors(root) == []

    def test_dependencies_must_exist(self, root):
        project(root, "a", depends_on=[{"project": "PROJ-ghost", "reason": "x"}])
        assert_one_error(graph.project_errors(root), "isn't a project doc")

    def test_self_dependency(self, root):
        project(root, "a", depends_on=[{"project": "PROJ-a", "reason": "x"}])
        assert_one_error(graph.project_errors(root), "depends_on itself")

    def test_dependency_cycle(self, root):
        project(root, "a", depends_on=[{"project": "PROJ-b", "reason": "x"}])
        project(root, "b", depends_on=[{"project": "PROJ-c", "reason": "x"}])
        project(root, "c", depends_on=[{"project": "PROJ-a", "reason": "x"}])
        errors = graph.project_errors(root)
        assert len(errors) == 1, errors
        assert "PROJ-a -> PROJ-b -> PROJ-c -> PROJ-a" in errors[0]

    def test_acyclic_diamond_is_clean(self, root):
        project(root, "base")
        project(root, "left", depends_on=[{"project": "PROJ-base", "reason": "x"}])
        project(root, "right", depends_on=[{"project": "PROJ-base", "reason": "x"}])
        project(root, "top", depends_on=[{"project": "PROJ-left", "reason": "x"}, {"project": "PROJ-right", "reason": "x"}])
        assert graph.project_errors(root) == []

    def test_duplicate_project_ids(self, root):
        project(root, "a")
        project(root, "b", id="PROJ-a")
        assert_one_error(graph.project_errors(root), "also used by")

    @pytest.mark.parametrize(
        ("project_status", "n", "rev_status"),
        [
            pytest.param(project_status, n, rev_status, id=f"{project_status}-project-{rev_status}-revision")
            for project_status in DECISION_GATE_ALLOWED
            for n, rev_status in enumerate(DECISION_GATE_REVISION_STATUSES, start=1)
        ],
    )
    def test_decision_gate_matrix(self, root, project_status, n, rev_status):
        for i, status in enumerate(DECISION_GATE_REVISION_STATUSES, start=1):
            revision(root, f"{i:04d}-x", 0, status=status)
        project(root, "p", status=project_status, decision=f"ADR-{n:04d}/0")
        errors = graph.project_errors(root)
        if rev_status in DECISION_GATE_ALLOWED[project_status]:
            assert errors == []
        else:
            assert_one_error(errors, f"but it is {rev_status}")

    def test_a_revision_dropping_back_to_working_stops_a_building_project(self, root):
        revision(root, "0001-x", 0, status="approved")
        project(root, "p", status="building", decision="ADR-0001/0")
        assert graph.project_errors(root) == []
        revision_path = root / "docs/decisions/0001-x/revision-000.md"
        revision_path.write_text(revision_path.read_text(encoding="utf-8").replace("status: approved", "status: working"), encoding="utf-8")
        assert_one_error(graph.project_errors(root), "needs decision ADR-0001/0 to be approved")

    def test_a_project_can_target_one_candidate_by_label(self, root):
        revision(root, "0001-x", 0, letter="a", status="approved")
        revision(root, "0001-x", 0, letter="b", status="abandoned")
        project(root, "p", status="building", decision="ADR-0001/0-a")
        assert graph.project_errors(root) == []
        (root / "docs/projects/p.md").unlink()
        project(root, "p", status="building", decision="ADR-0001/0-b")
        assert_one_error(graph.project_errors(root), "but it is abandoned")

    def test_a_bare_generation_does_not_resolve_when_it_has_lettered_candidates(self, root):
        revision(root, "0001-x", 0, letter="a", status="approved")
        revision(root, "0001-x", 0, letter="b", status="abandoned")
        project(root, "p", status="building", decision="ADR-0001/0")
        assert_one_error(graph.project_errors(root), "doesn't resolve")

    def test_unresolvable_decision(self, root):
        project(root, "p", status="building", decision="ADR-0099/0")
        assert_one_error(graph.project_errors(root), "doesn't resolve")

    @pytest.mark.parametrize("sibling_status", ["not-started", "building"])
    def test_done_may_name_an_approved_revision_while_a_sibling_is_unfinished(self, root, sibling_status):
        revision(root, "0001-x", 0, status="approved")
        project(root, "closing", status="done", decision="ADR-0001/0")
        project(root, "sibling", status=sibling_status, decision="ADR-0001/0")
        assert graph.project_errors(root) == []

    def test_done_naming_an_approved_revision_needs_an_unfinished_sibling(self, root):
        revision(root, "0001-x", 0, status="approved")
        project(root, "alone", status="done", decision="ADR-0001/0")
        assert_one_error(graph.project_errors(root), "another project not at done names it")

    def test_only_done_siblings_do_not_count(self, root):
        revision(root, "0001-x", 0, status="approved")
        project(root, "a", status="done", decision="ADR-0001/0")
        project(root, "b", status="done", decision="ADR-0001/0")
        errors = graph.project_errors(root)
        assert len(errors) == 2, errors

    def test_also_implements_is_not_naming(self, root):
        revision(root, "0001-x", 0, status="approved")
        project(root, "closing", status="done", decision="ADR-0001/0")
        project(root, "other", status="not-started", also_implements=["ADR-0001/0"])
        assert_one_error(graph.project_errors(root), "another project not at done names it")

    def test_a_sibling_on_a_different_revision_is_not_a_sibling(self, root):
        revision(root, "0001-x", 0, status="approved")
        revision(root, "0001-x", 1, status="working", supersedes=0)
        project(root, "closing", status="done", decision="ADR-0001/0")
        project(root, "other", status="not-started", decision="ADR-0001/1")
        assert_one_error(graph.project_errors(root), "another project not at done names it")

    def test_a_sibling_on_a_different_candidate_is_not_a_sibling(self, root):
        revision(root, "0001-x", 0, letter="a", status="approved")
        revision(root, "0001-x", 0, letter="b", status="abandoned")
        project(root, "closing", status="done", decision="ADR-0001/0-a")
        project(root, "other", status="not-started", decision="ADR-0001/0-b")
        errors = graph.project_errors(root)
        assert any("closing.md" in e and "another project not at done names it" in e for e in errors), errors

    def test_a_sibling_does_not_let_done_name_a_working_revision(self, root):
        revision(root, "0001-x", 0, status="working")
        project(root, "closing", status="done", decision="ADR-0001/0")
        project(root, "sibling", status="not-started", decision="ADR-0001/0")
        assert_one_error(graph.project_errors(root), "closing.md: status: done needs decision ADR-0001/0")

    def test_an_accepted_revision_with_an_unfinished_sibling_is_still_refused(self, root):
        revision(root, "0001-x", 0, status="accepted")
        project(root, "closing", status="done", decision="ADR-0001/0")
        project(root, "sibling", status="building", decision="ADR-0001/0")
        assert_one_error(graph.project_errors(root), "sibling.md: status: building needs decision ADR-0001/0 to be approved, but it is accepted")

    def test_projects_without_a_decision_are_never_gated(self, root):
        for i, status in enumerate(("not-started", "de-risking", "building", "done")):
            project(root, f"p{i}", status=status)
        assert graph.project_errors(root) == []


class TestHeadingErrors:
    def test_revision_zero_opens_with_its_number_and_title(self, root):
        revision(root, "0013-secret-storage", 0, body="# 0013. Secret storage\n\n## Context\n")
        assert graph.heading_errors(root) == []

    @pytest.mark.parametrize(
        "heading",
        [
            pytest.param("# Secret storage", id="no-number"),
            pytest.param("# 0013. Where secrets live", id="other-title"),
            pytest.param("# 0014. Secret storage", id="other-number"),
        ],
    )
    def test_revision_zero_with_another_heading_is_refused(self, root, heading):
        revision(root, "0013-secret-storage", 0, body=f"{heading}\n")
        assert_one_error(graph.heading_errors(root), "revision-000.md", "'# 0013. Secret storage'")

    def test_a_later_or_lettered_revision_names_its_own_solution(self, root):
        revision(root, "0013-secret-storage", 0, status="superseded", superseded_by=1, body="# 0013. Secret storage\n")
        revision(root, "0013-secret-storage", 1, status="accepted", supersedes=0, body="# A different heading\n")
        revision(root, "0014-other", 0, letter="a", body="# Pull-based agent, not a runner\n")
        revision(root, "0014-other", 0, letter="b", body="# Gitea Actions instead\n")
        assert graph.heading_errors(root) == []

    def test_a_status_body_line_is_refused_in_any_revision(self, root):
        revision(root, "0013-secret-storage", 0, body="# 0013. Secret storage\n\n**Status:** Accepted\n")
        assert_one_error(graph.heading_errors(root), "revision-000.md", "'**Status:**' body line")

    def test_status_wording_inside_prose_is_not_a_status_line(self, root):
        revision(root, "0013-secret-storage", 0, body="# 0013. Secret storage\n\nThe **Status:** field is not repeated here.\n")
        assert graph.heading_errors(root) == []


class TestChecklistErrors:
    ITEMS = ("Every criterion is met.", "Cross-references are updated or deleted.")

    def _checklist(self, *items: str) -> str:
        return "# Title\n\n## Closing checklist\n\nCopied from the template.\n\n" + "\n".join(f"- [ ] {item}" for item in items) + "\n"

    def _write(self, root, name: str, body: str):
        (root / "docs/projects").mkdir(parents=True, exist_ok=True)
        (root / f"docs/projects/{name}").write_text(body, encoding="utf-8")

    def test_a_project_with_the_template_items_passes(self, root):
        self._write(root, "TEMPLATE.md", self._checklist(*self.ITEMS))
        self._write(root, "alpha.md", self._checklist(*self.ITEMS, "An item of its own."))
        assert graph.checklist_errors(root) == []

    def test_wrapping_and_indentation_do_not_matter(self, root):
        self._write(root, "TEMPLATE.md", self._checklist(*self.ITEMS))
        self._write(root, "alpha.md", "## Closing checklist\n\n- [ ] Every criterion\n      is met.\n- [ ] Cross-references are updated\n      or deleted.\n")
        assert graph.checklist_errors(root) == []

    def test_an_item_added_to_the_template_is_required_everywhere(self, root):
        self._write(root, "TEMPLATE.md", self._checklist(*self.ITEMS, "No stage labels remain."))
        self._write(root, "alpha.md", self._checklist(*self.ITEMS))
        assert_one_error(graph.checklist_errors(root), "alpha.md", "missing 'No stage labels remain.'")

    def test_a_project_without_the_section_is_refused(self, root):
        self._write(root, "TEMPLATE.md", self._checklist(*self.ITEMS))
        self._write(root, "alpha.md", "# Title\n\n## Risks\n\n- none\n")
        assert_one_error(graph.checklist_errors(root), "alpha.md", "no '## Closing checklist' section")

    def test_the_readme_and_template_are_not_projects(self, root):
        self._write(root, "TEMPLATE.md", self._checklist(*self.ITEMS))
        self._write(root, "README.md", "# Projects\n")
        assert graph.checklist_errors(root) == []

    def test_without_a_template_there_is_nothing_to_compare(self, root):
        self._write(root, "alpha.md", "# Title\n")
        assert graph.checklist_errors(root) == []
