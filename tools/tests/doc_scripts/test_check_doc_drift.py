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

from _doc_fixtures import SCRIPTS, revision, write_doc

_spec = importlib.util.spec_from_file_location("check_doc_drift", SCRIPTS / "check-doc-drift.py")
drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drift)

INDEX_DIRS = ("docs", "docs/decisions", "docs/decisions/drafts", "docs/architecture", "docs/projects")


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
        revision(self.root, "0013-secret-storage", 1)
        drift.check_doc_indexes()
        self.assertEqual(len(drift.errors), 1, drift.errors)
        self.assertIn("lineage 0013-secret-storage/ exists but isn't linked", drift.errors[0])

    def test_linked_lineage_directory_passes(self):
        revision(self.root, "0013-secret-storage", 1)
        self.write("docs/decisions/README.md", "# Index\n\n[0013](0013-secret-storage/revision-001.md)\n")
        drift.check_doc_indexes()
        self.assertEqual(drift.errors, [])


class RepoFileLinkTest(_TmpRepo):
    def test_relative_link_to_an_existing_config_file_passes(self):
        self.write("docker/openbao/policy.hcl", "path {}\n")
        self.write("docs/decisions/0001-x/revision-001.md", "See [policy](../../../docker/openbao/policy.hcl).\n")
        drift.check_no_stale_anchors()
        self.assertEqual(drift.errors, [])

    def test_relative_link_to_a_missing_file_fails(self):
        self.write("docs/decisions/0001-x/revision-001.md", "See [policy](../../docker/openbao/policy.hcl).\n")
        drift.check_no_stale_anchors()
        self.assertEqual(len(drift.errors), 1, drift.errors)
        self.assertIn("../../docker/openbao/policy.hcl", drift.errors[0])

    def test_template_placeholders_are_skipped(self):
        self.write("docs/decisions/TEMPLATE.md", "[x](../nowhere/file.yaml)\n")
        drift.check_no_stale_anchors()
        self.assertEqual(drift.errors, [])


class NistAlignmentTest(_TmpRepo):
    def test_link_to_a_superseded_lineage_revision_fails(self):
        revision(self.root, "0013-secret-storage", 1, status="superseded", superseded_by=2)
        revision(self.root, "0013-secret-storage", 2, status="accepted", supersedes=1)
        self.write("docs/nist-800-53-alignment.md", "[old](decisions/0013-secret-storage/revision-001.md)\n")
        drift.check_nist_alignment_currency()
        self.assertEqual(len(drift.errors), 1, drift.errors)
        self.assertIn("now status: superseded", drift.errors[0])

    def test_link_to_the_accepted_revision_passes(self):
        revision(self.root, "0013-secret-storage", 1, status="superseded", superseded_by=2)
        revision(self.root, "0013-secret-storage", 2, status="accepted", supersedes=1)
        self.write("docs/nist-800-53-alignment.md", "[now](decisions/0013-secret-storage/revision-002.md)\n")
        drift.check_nist_alignment_currency()
        self.assertEqual(drift.errors, [])

    def test_flat_legacy_adrs_and_other_docs_still_behave(self):
        write_doc(
            self.root, "docs/decisions/0001-flat.md", {"id": "ADR-0001", "title": "t", "type": "adr", "status": "superseded", "superseded_by": "ADR-0002"}
        )
        self.write("docs/host-vars.md", "# Host vars\n")
        self.write("docs/nist-800-53-alignment.md", "[flat](decisions/0001-flat.md) and [other](host-vars.md)\n")
        drift.check_nist_alignment_currency()
        self.assertEqual(len(drift.errors), 1, drift.errors)
        self.assertIn("0001-flat.md", drift.errors[0])
