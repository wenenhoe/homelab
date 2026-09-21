"""Unit tests for doc_graph.py - the cross-document lineage, project,
dependency, and decision-gate rules. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import doc_graph as graph
from _doc_fixtures import project, revision


class _TmpRoot(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def assertOneError(self, errors: list[str], fragment: str) -> None:
        self.assertEqual(len(errors), 1, errors)
        self.assertIn(fragment, errors[0])


class HasOpenAssumptionsTest(unittest.TestCase):
    def test_bullets_under_the_heading_are_open(self):
        self.assertTrue(graph.has_open_assumptions("## Assumptions\n\n- **Claim:** x\n\n## Consequences\n"))

    def test_no_heading_or_no_bullets_is_resolved(self):
        self.assertFalse(graph.has_open_assumptions("## Context\n\ntext\n"))
        self.assertFalse(graph.has_open_assumptions("## Assumptions\n\nAll resolved.\n\n## Consequences\n- a bullet elsewhere\n"))

    def test_section_at_end_of_file(self):
        self.assertTrue(graph.has_open_assumptions("## Assumptions\n\n- open\n"))


class LineageErrorsTest(_TmpRoot):
    def test_clean_multi_revision_lineage(self):
        revision(self.root, "0013-secret-storage", 0, status="superseded", superseded_by=1)
        revision(self.root, "0013-secret-storage", 1, status="accepted", supersedes=0)
        revision(self.root, "0013-secret-storage", 2, status="working")
        self.assertEqual(graph.lineage_errors(self.root), [])

    def test_no_lineages_is_clean(self):
        self.assertEqual(graph.lineage_errors(self.root), [])

    def test_revision_numbers_start_at_zero_and_have_no_gaps(self):
        revision(self.root, "0001-a", 1)  # a lineage that starts at 001 has no original
        self.assertOneError(graph.lineage_errors(self.root), "000..NNN")
        revision(self.root, "0002-b", 0)
        revision(self.root, "0002-b", 2)
        self.assertTrue(any("0002-b" in e and "no gaps" in e for e in graph.lineage_errors(self.root)))

    def test_competing_candidates_are_lettered_from_a_with_none_missing(self):
        revision(self.root, "0001-a", 0, letter="a")
        revision(self.root, "0001-a", 0, letter="b")
        self.assertEqual(graph.lineage_errors(self.root), [])
        revision(self.root, "0002-b", 0, letter="a")
        revision(self.root, "0002-b", 0, letter="c")
        self.assertOneError(graph.lineage_errors(self.root), "none missing")

    def test_a_competing_generation_cannot_mix_lettered_and_unlettered(self):
        revision(self.root, "0001-a", 0)
        revision(self.root, "0001-a", 0, letter="b")
        self.assertOneError(graph.lineage_errors(self.root), "competing candidates")

    def test_a_lone_candidate_may_be_unlettered_or_a_but_not_b(self):
        revision(self.root, "0001-a", 0, letter="a")
        revision(self.root, "0002-b", 0)
        self.assertEqual(graph.lineage_errors(self.root), [])
        revision(self.root, "0003-c", 0, letter="b")
        self.assertOneError(graph.lineage_errors(self.root), "only candidate")

    def test_generations_not_files_must_be_contiguous(self):
        revision(self.root, "0001-a", 0, letter="a", status="abandoned")
        revision(self.root, "0001-a", 0, letter="b", status="working")
        revision(self.root, "0001-a", 1, status="working")
        self.assertEqual(graph.lineage_errors(self.root), [])
        revision(self.root, "0002-b", 0, letter="a", status="abandoned")
        revision(self.root, "0002-b", 0, letter="b", status="working")
        revision(self.root, "0002-b", 2, status="working")
        self.assertTrue(any("0002-b" in e and "no gaps" in e for e in graph.lineage_errors(self.root)))

    def test_choosing_one_candidate_requires_abandoning_the_others(self):
        for chosen in ("approved", "accepted"):
            with self.subTest(chosen=chosen):
                revision(self.root, "0001-a", 0, letter="a", status=chosen)
                revision(self.root, "0001-a", 0, letter="b", status="working")
                self.assertOneError(graph.lineage_errors(self.root), "competes with 0-a, which is decided")
                revision(self.root, "0001-a", 0, letter="b", status="abandoned")  # overwrites the same file
                self.assertEqual(graph.lineage_errors(self.root), [])

    def test_two_approved_candidates_are_never_valid(self):
        revision(self.root, "0001-a", 0, letter="a", status="approved")
        revision(self.root, "0001-a", 0, letter="b", status="approved")
        self.assertTrue(any("more than one decided" in e for e in graph.lineage_errors(self.root)))

    def test_working_candidates_may_all_stay_open(self):
        revision(self.root, "0001-a", 0, letter="a", status="working")
        revision(self.root, "0001-a", 0, letter="b", status="working")
        revision(self.root, "0001-a", 0, letter="c", status="abandoned")
        self.assertEqual(graph.lineage_errors(self.root), [])

    def test_only_one_candidate_per_generation_may_be_decided(self):
        revision(self.root, "0001-a", 0, letter="a", status="retired")
        revision(self.root, "0001-a", 0, letter="b", status="retired")
        self.assertTrue(any("more than one decided" in e for e in graph.lineage_errors(self.root)))

    def test_supersession_names_the_winning_candidate(self):
        revision(self.root, "0001-a", 0, letter="a", status="superseded", superseded_by=1)
        revision(self.root, "0001-a", 0, letter="b", status="abandoned")
        revision(self.root, "0001-a", 1, status="accepted", supersedes="0-a")
        self.assertEqual(graph.lineage_errors(self.root), [])

    def test_successor_must_name_the_candidate_that_was_superseded(self):
        revision(self.root, "0001-a", 0, letter="a", status="superseded", superseded_by=1)
        revision(self.root, "0001-a", 0, letter="b", status="abandoned")
        revision(self.root, "0001-a", 1, status="accepted", supersedes="0-b")
        self.assertTrue(any("must declare 'supersedes: 0-a'" in e for e in graph.lineage_errors(self.root)))

    def test_revision_zero_is_a_valid_original_and_first_supersession_target(self):
        revision(self.root, "0001-a", 0, status="superseded", superseded_by=1)
        revision(self.root, "0001-a", 1, status="accepted", supersedes=0)
        self.assertEqual(graph.lineage_errors(self.root), [])

    def test_only_one_accepted_revision(self):
        revision(self.root, "0001-a", 0, status="accepted")
        revision(self.root, "0001-a", 1, status="accepted")
        self.assertOneError(graph.lineage_errors(self.root), "only one may be")

    def test_duplicate_lineage_number(self):
        revision(self.root, "0001-a", 0)
        revision(self.root, "0001-b", 0)
        self.assertTrue(any("also used by" in e for e in graph.lineage_errors(self.root)))

    def test_title_and_topic_are_stable_across_revisions(self):
        revision(self.root, "0001-a", 0, status="abandoned")
        revision(self.root, "0001-a", 1, title="A different problem", topic="backup-recovery")
        errors = graph.lineage_errors(self.root)
        self.assertEqual(len(errors), 2, errors)

    def test_superseded_needs_an_accepted_successor(self):
        revision(self.root, "0001-a", 0, status="superseded", superseded_by=1)
        revision(self.root, "0001-a", 1, status="working", supersedes=0)
        self.assertOneError(graph.lineage_errors(self.root), "only superseded once its successor is accepted")

    def test_superseded_by_must_point_forward_and_exist(self):
        revision(self.root, "0001-a", 0, status="superseded", superseded_by=4)
        self.assertOneError(graph.lineage_errors(self.root), "isn't a later revision")

    def test_successor_must_declare_supersedes(self):
        revision(self.root, "0001-a", 0, status="superseded", superseded_by=1)
        revision(self.root, "0001-a", 1, status="accepted")
        self.assertOneError(graph.lineage_errors(self.root), "must declare 'supersedes: 0'")

    def test_accepted_successor_requires_the_target_to_be_superseded(self):
        revision(self.root, "0001-a", 0, status="accepted")
        revision(self.root, "0001-a", 1, status="accepted", supersedes=0)
        errors = graph.lineage_errors(self.root)
        self.assertTrue(any("must be status: superseded" in e for e in errors), errors)

    def test_working_successor_leaves_the_accepted_revision_alone(self):
        revision(self.root, "0001-a", 0, status="accepted")
        revision(self.root, "0001-a", 1, status="working", supersedes=0)
        self.assertEqual(graph.lineage_errors(self.root), [])

    def test_supersedes_must_point_backward(self):
        revision(self.root, "0001-a", 0, status="working", supersedes=1)
        revision(self.root, "0001-a", 1, status="working")
        self.assertOneError(graph.lineage_errors(self.root), "isn't an earlier revision")

    def test_cross_lineage_references_must_resolve(self):
        revision(self.root, "0001-a", 0, narrows="ADR-0009", related=["ADR-0008"])
        errors = graph.lineage_errors(self.root)
        self.assertEqual(len(errors), 2, errors)
        revision(self.root, "0002-b", 0, narrows="ADR-0002")
        self.assertTrue(any("narrows its own lineage" in e for e in graph.lineage_errors(self.root)))

    def test_narrows_and_related_between_real_lineages_are_clean(self):
        revision(self.root, "0015-expiry", 0, status="accepted")
        revision(self.root, "0016-oci", 0, status="accepted", narrows="ADR-0015", related=["ADR-0015"])
        self.assertEqual(graph.lineage_errors(self.root), [])

    def test_former_id_must_not_be_a_live_lineage(self):
        revision(self.root, "0013-a", 0, status="accepted", former_ids=["ADR-0027"])
        self.assertEqual(graph.lineage_errors(self.root), [])
        revision(self.root, "0027-b", 0)
        self.assertOneError(graph.lineage_errors(self.root), "still a live lineage")

    def test_former_id_claimed_twice(self):
        revision(self.root, "0001-a", 0, former_ids=["ADR-0050"])
        revision(self.root, "0002-b", 0, former_ids=["ADR-0050"])
        self.assertOneError(graph.lineage_errors(self.root), "already claimed")


class OpenAssumptionErrorsTest(_TmpRoot):
    OPEN = "## Assumptions\n\n- **Claim:** it works\n"

    def test_approved_and_accepted_cannot_carry_open_assumptions(self):
        for status in ("approved", "accepted"):
            with self.subTest(status=status):
                revision(self.root, f"000{1 if status == 'approved' else 2}-x", 0, status=status, body=self.OPEN)
        errors = graph.open_assumption_errors(self.root)
        self.assertEqual(len(errors), 2, errors)

    def test_working_may_carry_them_and_resolved_docs_pass(self):
        revision(self.root, "0001-x", 0, status="working", body=self.OPEN)
        revision(self.root, "0002-y", 0, status="accepted", body="## Context\n\nfacts\n")
        self.assertEqual(graph.open_assumption_errors(self.root), [])


class ProjectErrorsTest(_TmpRoot):
    def test_no_projects_is_clean(self):
        self.assertEqual(graph.project_errors(self.root), [])

    def test_dependencies_must_exist(self):
        project(self.root, "a", depends_on=[{"project": "PROJ-ghost", "reason": "x"}])
        self.assertOneError(graph.project_errors(self.root), "isn't a project doc")

    def test_self_dependency(self):
        project(self.root, "a", depends_on=[{"project": "PROJ-a", "reason": "x"}])
        self.assertOneError(graph.project_errors(self.root), "depends_on itself")

    def test_dependency_cycle(self):
        project(self.root, "a", depends_on=[{"project": "PROJ-b", "reason": "x"}])
        project(self.root, "b", depends_on=[{"project": "PROJ-c", "reason": "x"}])
        project(self.root, "c", depends_on=[{"project": "PROJ-a", "reason": "x"}])
        errors = graph.project_errors(self.root)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("PROJ-a -> PROJ-b -> PROJ-c -> PROJ-a", errors[0])

    def test_acyclic_diamond_is_clean(self):
        project(self.root, "base")
        project(self.root, "left", depends_on=[{"project": "PROJ-base", "reason": "x"}])
        project(self.root, "right", depends_on=[{"project": "PROJ-base", "reason": "x"}])
        project(self.root, "top", depends_on=[{"project": "PROJ-left", "reason": "x"}, {"project": "PROJ-right", "reason": "x"}])
        self.assertEqual(graph.project_errors(self.root), [])

    def test_duplicate_project_ids(self):
        project(self.root, "a")
        project(self.root, "b", id="PROJ-a")
        self.assertOneError(graph.project_errors(self.root), "also used by")

    def test_decision_gate_matrix(self):
        allowed = {
            "not-started": {"working", "approved"},
            "de-risking": {"working"},
            "building": {"approved"},
            "done": {"accepted"},
        }
        statuses = ["working", "approved", "accepted", "abandoned", "retired"]
        for n, rev_status in enumerate(statuses, start=1):
            extra = {"superseded_by": 8} if rev_status == "superseded" else {}
            revision(self.root, f"{n:04d}-x", 0, status=rev_status, **extra)
        for project_status, ok_revisions in allowed.items():
            for n, rev_status in enumerate(statuses, start=1):
                with self.subTest(project=project_status, revision=rev_status):
                    for old in (self.root / "docs/projects").glob("*.md"):
                        old.unlink()
                    project(self.root, "p", status=project_status, decision=f"ADR-{n:04d}/0")
                    errors = graph.project_errors(self.root)
                    if rev_status in ok_revisions:
                        self.assertEqual(errors, [])
                    else:
                        self.assertOneError(errors, f"but it is {rev_status}")

    def test_a_revision_dropping_back_to_working_stops_a_building_project(self):
        revision(self.root, "0001-x", 0, status="approved")
        project(self.root, "p", status="building", decision="ADR-0001/0")
        self.assertEqual(graph.project_errors(self.root), [])
        revision_path = self.root / "docs/decisions/0001-x/revision-000.md"
        revision_path.write_text(revision_path.read_text(encoding="utf-8").replace("status: approved", "status: working"), encoding="utf-8")
        self.assertOneError(graph.project_errors(self.root), "needs decision ADR-0001/0 to be approved")

    def test_a_project_can_target_one_candidate_by_label(self):
        revision(self.root, "0001-x", 0, letter="a", status="approved")
        revision(self.root, "0001-x", 0, letter="b", status="abandoned")
        project(self.root, "p", status="building", decision="ADR-0001/0-a")
        self.assertEqual(graph.project_errors(self.root), [])
        (self.root / "docs/projects/p.md").unlink()
        project(self.root, "p", status="building", decision="ADR-0001/0-b")
        self.assertOneError(graph.project_errors(self.root), "but it is abandoned")

    def test_a_bare_generation_does_not_resolve_when_it_has_lettered_candidates(self):
        revision(self.root, "0001-x", 0, letter="a", status="approved")
        revision(self.root, "0001-x", 0, letter="b", status="abandoned")
        project(self.root, "p", status="building", decision="ADR-0001/0")
        self.assertOneError(graph.project_errors(self.root), "doesn't resolve")

    def test_unresolvable_decision(self):
        project(self.root, "p", status="building", decision="ADR-0099/0")
        self.assertOneError(graph.project_errors(self.root), "doesn't resolve")

    def test_projects_without_a_decision_are_never_gated(self):
        for i, status in enumerate(("not-started", "de-risking", "building", "done")):
            project(self.root, f"p{i}", status=status)
        self.assertEqual(graph.project_errors(self.root), [])
