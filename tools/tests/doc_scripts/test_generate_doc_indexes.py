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

from _doc_fixtures import SCRIPTS, project, revision, write_doc

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

    def test_legacy_statuses_render_as_before(self):
        project(self.root, "a", status="in-progress")
        project(self.root, "b", status="blocked", blocked_reason="waiting on a draft")
        project(self.root, "c", status="not-started")
        self.assertEqual(
            self.rows(),
            [
                "| [`a.md`](a.md) | In progress | a summary |",
                "| [`b.md`](b.md) | Blocked: waiting on a draft | b summary |",
                "| [`c.md`](c.md) | Not started | c summary |",
            ],
        )

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
            1,
            title="Container access to the Docker API",
            topic="deployment-platform",
            status="accepted",
            solution="Socket proxy",
        )
        revision(self.root, "0017-store-recovery", 1, title="Recovering the store", topic="secrets-store", status="accepted", solution="Split secrets")
        revision(self.root, "0001-host-config", 1, title="Host configuration", topic="deployment-platform", status="accepted", solution="Ansible")
        out = gen.render_lineages_index(self.root)
        self.assertLess(out.index("### Deployment & platform"), out.index("### Secrets store"))
        self.assertNotIn("### Backup", out)
        self.assertLess(out.index("0001-host-config"), out.index("0004-docker-api-access"))
        self.assertIn(
            "| [0004](0004-docker-api-access/revision-001.md) | **Container access to the Docker API** — Where secrets live. | Socket proxy | Accepted | — |",
            out,
        )

    def test_multi_revision_lineage_shows_current_and_pending(self):
        revision(self.root, "0013-secret-storage", 1, status="superseded", superseded_by=2, solution="File cache")
        revision(self.root, "0013-secret-storage", 2, status="accepted", supersedes=1, solution="OpenBao", former_ids=["ADR-0027"])
        revision(self.root, "0013-secret-storage", 3, status="working", solution="Something newer")
        out = gen.render_lineages_index(self.root)
        self.assertIn("[0013](0013-secret-storage/revision-002.md)", out)
        self.assertIn("| OpenBao | Accepted (revision 2) | Revision 3 working; Formerly ADR-0027 |", out)

    def test_narrowed_by_and_related_back_pointers(self):
        revision(self.root, "0015-expiry", 1, status="accepted", topic="cloud-credentials", title="Credential expiry")
        revision(self.root, "0016-oci", 1, status="accepted", topic="cloud-credentials", title="OCI credentials", narrows="ADR-0015", related=["ADR-0014"])
        revision(self.root, "0014-r2", 1, status="accepted", topic="cloud-credentials", title="R2 rotation credential")
        out = gen.render_lineages_index(self.root)
        rows = {line.split("|")[1].strip()[1:5]: line for line in out.splitlines() if line.startswith("| [")}
        self.assertIn("Narrowed by [0016](0016-oci/revision-001.md)", rows["0015"])
        self.assertNotIn("Narrowed by", rows["0016"])
        self.assertIn("Related: [0014](0014-r2/revision-001.md)", rows["0016"])
        self.assertIn("Related: [0016](0016-oci/revision-001.md)", rows["0014"])

    def test_pipes_in_text_are_escaped(self):
        revision(self.root, "0001-x", 1, status="accepted", solution="a | b")
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


class DraftsTableTest(_TmpRoot):
    def test_draft_with_and_without_a_linking_project(self):
        write_doc(self.root, "docs/decisions/drafts/linked.md", {"id": "DRAFT-linked", "title": "t", "type": "draft-adr", "status": "de-risking"})
        write_doc(self.root, "docs/decisions/drafts/loose.md", {"id": "DRAFT-loose", "title": "t", "type": "draft-adr", "status": "decided"})
        write_doc(
            self.root, "docs/projects/p.md", {"id": "PROJ-p", "title": "p", "type": "project", "status": "done", "summary": "s"}, body="See drafts/linked.md\n"
        )
        rows = gen.render_drafts_table(self.root).splitlines()[2:]
        self.assertEqual(rows[0], "| [`linked.md`](linked.md) | De-risking | [`p.md`](../../projects/p.md) |")
        self.assertEqual(rows[1], "| [`loose.md`](loose.md) | Decided | — |")
