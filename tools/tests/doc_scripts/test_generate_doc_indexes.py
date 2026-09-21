"""Unit tests for generate-doc-indexes.py - table rendering and
section replacement. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from _doc_fixtures import SCRIPTS, project, revision

_spec = importlib.util.spec_from_file_location("generate_doc_indexes", SCRIPTS / "generate-doc-indexes.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


class _TmpRoot(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)


class ProjectsTableTest(_TmpRoot):
    def rows(self) -> list[str]:
        return gen.render_projects_table(self.root).splitlines()[2:]

    def test_not_started_and_sort_order(self):
        project(self.root, "a", status="not-started")
        project(self.root, "b", status="not-started")
        self.assertEqual(self.rows(), ["| [`a.md`](a.md) | Not started | a summary |", "| [`b.md`](b.md) | Not started | b summary |"])

    def test_lifecycle_statuses_and_the_blocked_flag(self):
        project(self.root, "a", status="de-risking")
        project(self.root, "b", status="building", blocked=True, blocked_reason="needs new hardware")
        project(self.root, "c", status="done")
        self.assertEqual(
            self.rows(),
            [
                "| [`a.md`](a.md) | De-risking | a summary |",
                "| [`b.md`](b.md) | Building — blocked: needs new hardware | b summary |",
                "| [`c.md`](c.md) | Done | c summary |",
            ],
        )

    def test_waiting_on_an_existing_predecessor(self):
        project(self.root, "base", status="building")
        project(self.root, "next", depends_on=[{"project": "PROJ-base", "reason": "needs its output"}])
        self.assertEqual(self.rows()[1], "| [`next.md`](next.md) | Not started — waiting on [`base.md`](base.md) | next summary |")

    def test_blocked_flag_and_dependency_combine(self):
        project(self.root, "base")
        project(self.root, "next", status="building", blocked=True, blocked_reason="r", depends_on=[{"project": "PROJ-base", "reason": "x"}])
        self.assertIn("Building — blocked: r — waiting on [`base.md`](base.md)", self.rows()[1])


class InitiativesTableTest(_TmpRoot):
    def test_groups_by_label_and_skips_unlabelled(self):
        project(self.root, "a", super_project="pull-based-cd", status="building")
        project(self.root, "b", super_project="pull-based-cd")
        project(self.root, "c")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            table = gen.render_initiatives_table(self.root)
        self.assertEqual(
            table.splitlines()[2:],
            ["| `pull-based-cd` | — | — | [`a.md`](a.md) | Building |", "| `pull-based-cd` | — | — | [`b.md`](b.md) | Not started |"],
        )
        self.assertEqual(err.getvalue(), "")

    def test_track_and_phase_columns_and_ordering(self):
        project(self.root, "late", super_project="cd", track="security", phase="hardening")
        project(self.root, "early", super_project="cd", track="security", phase="bootstrap")
        project(self.root, "infra", super_project="cd", track="agent")
        project(self.root, "loose", super_project="cd")
        table = gen.render_initiatives_table(self.root)
        self.assertEqual(
            [line.split("|")[4].strip() for line in table.splitlines()[2:]],
            ["[`loose.md`](loose.md)", "[`infra.md`](infra.md)", "[`early.md`](early.md)", "[`late.md`](late.md)"],
        )
        self.assertIn("| `cd` | `security` | `bootstrap` | [`early.md`](early.md) |", table)

    def _order(self) -> list[str]:
        with contextlib.redirect_stderr(io.StringIO()):
            table = gen.render_initiatives_table(self.root)
        return [line.split("|")[4].strip().split("`")[1] for line in table.splitlines()[2:]]

    def test_tracks_read_in_build_order_not_alphabetical(self):
        project(self.root, "core", super_project="t", track="provisioning")
        project(self.root, "rehearse", super_project="t", track="migration", depends_on=[{"project": "PROJ-core", "reason": "x"}])
        project(self.root, "day2", super_project="t", track="opnsense", depends_on=[{"project": "PROJ-rehearse", "reason": "x"}])
        self.assertEqual(self._order(), ["core.md", "rehearse.md", "day2.md"])

    def test_numbered_phases_order_a_track_even_when_names_sort_the_other_way(self):
        project(self.root, "cutover", super_project="t", track="migration", phase="2-cutover")
        project(self.root, "rehearsal", super_project="t", track="migration", phase="1-rehearsal")
        self.assertEqual(self._order(), ["rehearsal.md", "cutover.md"])

    def test_an_explicit_phase_order_beats_inferred_depth(self):
        project(self.root, "outside", super_project="t", track="y")
        project(self.root, "first", super_project="t", track="x", phase="1-first", depends_on=[{"project": "PROJ-outside", "reason": "x"}])
        project(self.root, "second", super_project="t", track="x", phase="2-second")
        # `first` is deeper than `second`, but its phase says it reads first
        self.assertEqual(self._order(), ["first.md", "second.md", "outside.md"])

    def test_within_a_track_dependency_depth_orders_projects(self):
        project(self.root, "a-last", super_project="t", track="x", depends_on=[{"project": "PROJ-z-first", "reason": "x"}])
        project(self.root, "z-first", super_project="t", track="x")
        self.assertEqual(self._order(), ["z-first.md", "a-last.md"])

    def test_independent_tracks_fall_back_to_name(self):
        project(self.root, "b", super_project="t", track="beta")
        project(self.root, "a", super_project="t", track="alpha")
        self.assertEqual(self._order(), ["a.md", "b.md"])

    def test_a_tracks_rows_stay_together_when_the_chain_weaves_between_tracks(self):
        project(self.root, "early", super_project="t", track="alpha")
        project(self.root, "mid", super_project="t", track="beta", depends_on=[{"project": "PROJ-early", "reason": "x"}])
        project(self.root, "late", super_project="t", track="alpha", depends_on=[{"project": "PROJ-mid", "reason": "x"}])
        # by depth alone this would interleave alpha, beta, alpha
        self.assertEqual(self._order(), ["early.md", "late.md", "mid.md"])

    def test_initiatives_stay_grouped(self):
        project(self.root, "y1", super_project="y")
        project(self.root, "x2", super_project="x", depends_on=[{"project": "PROJ-x1", "reason": "x"}])
        project(self.root, "x1", super_project="x")
        project(self.root, "y2", super_project="y", depends_on=[{"project": "PROJ-y1", "reason": "x"}])
        self.assertEqual(self._order(), ["x1.md", "x2.md", "y1.md", "y2.md"])

    def test_a_dependency_cycle_does_not_hang_the_generator(self):
        project(self.root, "a", super_project="t", depends_on=[{"project": "PROJ-b", "reason": "x"}])
        project(self.root, "b", super_project="t", depends_on=[{"project": "PROJ-a", "reason": "x"}])
        self.assertEqual(sorted(self._order()), ["a.md", "b.md"])

    def test_a_dependency_on_a_missing_project_is_ignored(self):
        project(self.root, "a", super_project="t", depends_on=[{"project": "PROJ-ghost", "reason": "x"}])
        project(self.root, "b", super_project="t")
        self.assertEqual(self._order(), ["a.md", "b.md"])

    def test_single_use_label_warns_but_still_renders(self):
        project(self.root, "a", super_project="typo-label")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            table = gen.render_initiatives_table(self.root)
        self.assertIn("typo-label", err.getvalue())
        self.assertIn("`typo-label`", table)

    def test_no_labels(self):
        project(self.root, "a")
        self.assertEqual(gen.render_initiatives_table(self.root), "No project is grouped into an initiative.")


class LineagesIndexTest(_TmpRoot):
    def test_empty(self):
        self.assertEqual(gen.render_lineages_index(self.root), "No decision lineages yet.")

    def test_groups_by_topic_in_vocabulary_order(self):
        revision(
            self.root,
            "0004-docker-api-access",
            0,
            title="Container access to the Docker API",
            topic="deployment-platform",
            status="accepted",
            solution="Socket proxy",
        )
        revision(self.root, "0017-store-recovery", 0, title="Recovering the store", topic="secrets-store", status="accepted", solution="Split secrets")
        revision(self.root, "0001-host-config", 0, title="Host configuration", topic="deployment-platform", status="accepted", solution="Ansible")
        out = gen.render_lineages_index(self.root)
        self.assertLess(out.index("### Deployment & platform"), out.index("### Secrets store"))
        self.assertNotIn("### Backup", out)
        self.assertLess(out.index("0001-host-config"), out.index("0004-docker-api-access"))
        self.assertIn(
            "| [0004](0004-docker-api-access/revision-000.md) | **Container access to the Docker API** — Where secrets live. | Socket proxy | Accepted | — |",
            out,
        )

    def test_multi_revision_lineage_shows_current_and_pending(self):
        revision(self.root, "0013-secret-storage", 0, status="superseded", superseded_by=1, solution="File cache")
        revision(self.root, "0013-secret-storage", 1, status="accepted", supersedes=0, solution="OpenBao", former_ids=["ADR-0027"])
        revision(self.root, "0013-secret-storage", 2, status="working", solution="Something newer")
        out = gen.render_lineages_index(self.root)
        self.assertIn("[0013](0013-secret-storage/revision-001.md)", out)
        self.assertIn("| OpenBao | Accepted (revision 1) | Revision 2 working; Formerly ADR-0027 |", out)

    def test_the_original_is_labelled_when_a_successor_exists(self):
        revision(self.root, "0013-secret-storage", 0, status="accepted", solution="File cache")
        revision(self.root, "0013-secret-storage", 1, status="working", supersedes=0, solution="OpenBao")
        out = gen.render_lineages_index(self.root)
        self.assertIn("| File cache | Accepted (original) | Revision 1 working |", out)
        self.assertNotIn("revision 0", out)

    def test_competing_candidates_are_shown_as_undecided(self):
        revision(self.root, "0044-trigger", 0, letter="a", status="working", solution="Pull-based agent")
        revision(self.root, "0044-trigger", 0, letter="b", status="working", solution="Private Gitea")
        out = gen.render_lineages_index(self.root)
        self.assertIn("[0044](0044-trigger/revision-000-a.md)", out)
        self.assertIn("Undecided between: (000-a) Pull-based agent; or (000-b) Private Gitea", out)
        self.assertIn("Working (000-a), Working (000-b)", out)
        self.assertNotIn("| Private Gitea |", out)  # the newest candidate must not be presented as the current solution

    def test_open_revisions_in_different_generations_are_also_undecided(self):
        revision(self.root, "0044-trigger", 0, status="working", solution="A")
        revision(self.root, "0044-trigger", 1, status="working", solution="B")
        self.assertIn("Undecided between: (000) A; or (001) B", gen.render_lineages_index(self.root))

    def test_an_approved_revision_with_a_successor_in_flight_is_also_undecided(self):
        revision(self.root, "0044-trigger", 0, status="approved", solution="A")
        revision(self.root, "0044-trigger", 1, status="working", supersedes=0, solution="B")
        self.assertIn("Approved (000), Working (001)", gen.render_lineages_index(self.root))

    def test_the_winning_candidate_is_labelled_and_pending_replacements_are_listed(self):
        revision(self.root, "0044-trigger", 0, letter="a", status="accepted", solution="A")
        revision(self.root, "0044-trigger", 0, letter="b", status="abandoned", solution="B")
        revision(self.root, "0044-trigger", 1, letter="a", status="working", supersedes="0-a", solution="C")
        revision(self.root, "0044-trigger", 1, letter="b", status="working", supersedes="0-a", solution="D")
        out = gen.render_lineages_index(self.root)
        self.assertNotIn("Undecided", out)
        self.assertIn("| A | Accepted (original (a)) | Revision 1-a working; Revision 1-b working |", out)

    def test_an_accepted_revision_means_not_undecided(self):
        revision(self.root, "0044-trigger", 0, status="accepted", solution="A")
        revision(self.root, "0044-trigger", 1, status="working", supersedes=0, solution="B")
        out = gen.render_lineages_index(self.root)
        self.assertNotIn("Undecided", out)
        self.assertIn("| A | Accepted (original) | Revision 1 working |", out)

    def test_abandoned_alternatives_do_not_make_it_undecided(self):
        revision(self.root, "0044-trigger", 0, status="abandoned", solution="A")
        revision(self.root, "0044-trigger", 1, status="working", solution="B")
        out = gen.render_lineages_index(self.root)
        self.assertNotIn("Undecided", out)
        self.assertIn("| B | Working (revision 1) |", out)

    def test_narrowed_by_and_related_back_pointers(self):
        revision(self.root, "0015-expiry", 0, status="accepted", topic="cloud-credentials", title="Credential expiry")
        revision(self.root, "0016-oci", 0, status="accepted", topic="cloud-credentials", title="OCI credentials", narrows="ADR-0015", related=["ADR-0014"])
        revision(self.root, "0014-r2", 0, status="accepted", topic="cloud-credentials", title="R2 rotation credential")
        out = gen.render_lineages_index(self.root)
        rows = {line.split("|")[1].strip()[1:5]: line for line in out.splitlines() if line.startswith("| [")}
        self.assertIn("Narrowed by [0016](0016-oci/revision-000.md)", rows["0015"])
        self.assertNotIn("Narrowed by", rows["0016"])
        self.assertIn("Related: [0014](0014-r2/revision-000.md)", rows["0016"])
        self.assertIn("Related: [0016](0016-oci/revision-000.md)", rows["0014"])

    def test_pipes_in_text_are_escaped(self):
        revision(self.root, "0001-x", 0, status="accepted", solution="a | b")
        self.assertIn(r"a \| b", gen.render_lineages_index(self.root))


class SectionReplacementTest(_TmpRoot):
    DOC = "# T\n\nintro\n\n## Index\n\nold\n\n## Other\n\nkeep\n"

    def test_replaces_only_the_named_section(self):
        self.assertEqual(gen.replace_section(self.DOC, "Index", "new"), "# T\n\nintro\n\n## Index\n\nnew\n\n## Other\n\nkeep\n")

    def test_h3_headings_inside_a_section_do_not_end_it(self):
        doc = "## Lineages\n\n### A\n\nold\n\n### B\n\nold\n\n## Next\n\nkeep\n"
        self.assertEqual(gen.replace_section(doc, "Lineages", "new"), "## Lineages\n\nnew\n\n## Next\n\nkeep\n")

    def test_missing_required_section_fails(self):
        path = self.root / "README.md"
        path.write_text("# T\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "couldn't find"):
            gen.regenerate(path, "Index", "x")

    def test_optional_section_is_skipped_when_absent(self):
        path = self.root / "README.md"
        path.write_text("# T\n\n## Other\n\nkeep\n", encoding="utf-8")
        self.assertFalse(gen.regenerate(path, "Lineages", "x", optional=True))
        self.assertEqual(path.read_text(encoding="utf-8"), "# T\n\n## Other\n\nkeep\n")

    def test_optional_section_is_replaced_when_present(self):
        path = self.root / "README.md"
        path.write_text("# T\n\n## Lineages\n\nold\n", encoding="utf-8")
        self.assertTrue(gen.regenerate(path, "Lineages", "new", optional=True))
        self.assertEqual(path.read_text(encoding="utf-8"), "# T\n\n## Lineages\n\nnew\n")
