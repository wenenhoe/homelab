"""Unit tests for the decision-lineage-aware parts of
check-doc-drift.py: index coverage of lineage directories, relative
links to non-markdown files, and the NIST-link supersession check.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from _doc_fixtures import SCRIPTS, revision

_spec = importlib.util.spec_from_file_location("check_doc_drift", SCRIPTS / "check-doc-drift.py")
drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drift)

INDEX_DIRS = ("docs", "docs/decisions", "docs/architecture", "docs/projects")


class _TmpRepo(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._original_root = drift.ROOT
        drift.ROOT = self.root
        drift.errors.clear()
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        drift.ROOT = self._original_root
        drift.errors.clear()

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class LineageIndexTest(_TmpRepo):
    def setUp(self) -> None:
        super().setUp()
        for d in INDEX_DIRS:
            self.write(f"{d}/README.md", "# Index\n")

    def test_lineage_directory_must_appear_in_the_decisions_index(self):
        revision(self.root, "0013-secret-storage", 0)
        drift.check_doc_indexes()
        self.assertEqual(len(drift.errors), 1, drift.errors)
        self.assertIn("lineage 0013-secret-storage/ exists but isn't linked", drift.errors[0])

    def test_linked_lineage_directory_passes(self):
        revision(self.root, "0013-secret-storage", 0)
        self.write("docs/decisions/README.md", "# Index\n\n[0013](0013-secret-storage/revision-000.md)\n")
        drift.check_doc_indexes()
        self.assertEqual(drift.errors, [])


class RepoFileLinkTest(_TmpRepo):
    def test_relative_link_to_an_existing_config_file_passes(self):
        self.write("docker/openbao/policy.hcl", "path {}\n")
        self.write("docs/decisions/0001-x/revision-000.md", "See [policy](../../../docker/openbao/policy.hcl).\n")
        drift.check_no_stale_anchors()
        self.assertEqual(drift.errors, [])

    def test_relative_link_to_a_missing_file_fails(self):
        self.write("docs/decisions/0001-x/revision-000.md", "See [policy](../../docker/openbao/policy.hcl).\n")
        drift.check_no_stale_anchors()
        self.assertEqual(len(drift.errors), 1, drift.errors)
        self.assertIn("../../docker/openbao/policy.hcl", drift.errors[0])

    def test_template_placeholders_are_skipped(self):
        self.write("docs/decisions/TEMPLATE.md", "[x](../nowhere/file.yaml)\n")
        drift.check_no_stale_anchors()
        self.assertEqual(drift.errors, [])


class NistAlignmentTest(_TmpRepo):
    def test_link_to_a_superseded_lineage_revision_fails(self):
        revision(self.root, "0013-secret-storage", 0, status="superseded", superseded_by=1)
        revision(self.root, "0013-secret-storage", 1, status="accepted", supersedes=0)
        self.write("docs/nist-800-53-alignment.md", "[old](decisions/0013-secret-storage/revision-000.md)\n")
        drift.check_nist_alignment_currency()
        self.assertEqual(len(drift.errors), 1, drift.errors)
        self.assertIn("now status: superseded", drift.errors[0])

    def test_link_to_the_accepted_revision_passes(self):
        revision(self.root, "0013-secret-storage", 0, status="superseded", superseded_by=1)
        revision(self.root, "0013-secret-storage", 1, status="accepted", supersedes=0)
        self.write("docs/nist-800-53-alignment.md", "[now](decisions/0013-secret-storage/revision-001.md)\n")
        drift.check_nist_alignment_currency()
        self.assertEqual(drift.errors, [])

    def test_links_outside_lineages_are_ignored(self):
        self.write("docs/decisions/0001-flat.md", "# not a lineage\n")
        self.write("docs/host-vars.md", "# Host vars\n")
        self.write("docs/nist-800-53-alignment.md", "[flat](decisions/0001-flat.md) and [other](host-vars.md)\n")
        drift.check_nist_alignment_currency()
        self.assertEqual(drift.errors, [])


class DecisionPathMentionTest(_TmpRepo):
    def setUp(self) -> None:
        super().setUp()
        self.write("docs/decisions/0001-x/revision-000.md", "# real\n")
        self.write("docs/decisions/README.md", "# Index\n")

    def test_existing_paths_pass_in_every_scanned_file_type(self):
        real = "docs/decisions/0001-x/revision-000.md"
        self.write("tools/tool.py", f"# see {real}\n")
        self.write("ansible/roles/r/tasks/main.yaml", f"# see {real}\n")
        self.write("tools/run.sh", f"# see {real}\n")
        self.write("pyproject.toml", f"# see {real}\n")
        self.write("docs/topic.md", f"See `{real}` and docs/decisions/README.md#anything.\n")
        drift.check_decision_path_mentions()
        self.assertEqual(drift.errors, [])

    def test_a_missing_path_fails_in_comments_and_docs(self):
        self.write("tools/tool.py", "# see docs/decisions/0009-gone/revision-000.md.\n")
        self.write("docs/topic.md", "See docs/decisions/0008-gone/revision-001.md for more.\n")
        drift.check_decision_path_mentions()
        self.assertEqual(len(drift.errors), 2, drift.errors)
        self.assertTrue(any("tool.py" in e and "0009-gone/revision-000.md" in e for e in drift.errors))
        self.assertTrue(any("topic.md" in e and "0008-gone/revision-001.md" in e for e in drift.errors))

    def test_a_missing_path_is_caught_in_every_scanned_extension(self):
        missing = "docs/decisions/0009-gone/revision-000.md"
        for name in ("a.py", "a.yaml", "a.yml", "a.sh", "a.toml", "a.hcl", "a.j2", "a.md"):
            with self.subTest(name=name):
                drift.errors.clear()
                self.write(f"scan/{name}", f"# see {missing}\n")
                drift.check_decision_path_mentions()
                self.assertEqual(len(drift.errors), 1, drift.errors)
                (self.root / "scan" / name).unlink()

    def test_unscanned_extensions_are_ignored(self):
        self.write("notes.txt", "docs/decisions/0009-gone/revision-000.md\n")
        drift.check_decision_path_mentions()
        self.assertEqual(drift.errors, [])

    def test_old_flat_style_path_fails_after_a_refile(self):
        self.write("tools/tool.py", "# docs/decisions/0001-old-flat-name.md\n")
        drift.check_decision_path_mentions()
        self.assertEqual(len(drift.errors), 1, drift.errors)

    def test_placeholders_and_names_without_a_path_are_ignored(self):
        self.write("docs/topic.md", "Pattern docs/decisions/NNNN-slug/revision-NNN.md; the draft `deleted-draft` was removed.\n")
        drift.check_decision_path_mentions()
        self.assertEqual(drift.errors, [])

    def test_test_fixtures_are_exempt(self):
        self.write("tools/tests/doc_scripts/fixture.py", 'x = "docs/decisions/0099-fake/revision-000.md"\n')
        drift.check_decision_path_mentions()
        self.assertEqual(drift.errors, [])
