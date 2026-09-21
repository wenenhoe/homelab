"""Unit tests for doc_frontmatter.py - the schema of record for decision
and project docs. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import doc_frontmatter as fm_mod
from _doc_fixtures import project, revision, write_doc


class _TmpRoot(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)


class DocKindTest(unittest.TestCase):
    def test_kind_is_decided_by_location(self):
        cases = {
            "docs/decisions/0013-secret-storage/revision-002.md": "adr-revision",
            "docs/projects/cd-agent.md": "project",
        }
        for rel, kind in cases.items():
            with self.subTest(rel=rel):
                self.assertEqual(fm_mod.doc_kind(Path("/repo") / rel), kind)

    def test_flat_files_and_drafts_are_rejected(self):
        for rel in ("docs/decisions/0013-secret-storage.md", "docs/decisions/drafts/some-draft.md"):
            with self.subTest(rel=rel), self.assertRaisesRegex(SystemExit, "lineage directories"):
                fm_mod.doc_kind(Path("/repo") / rel)

    def test_outside_decisions_and_projects_is_rejected(self):
        with self.assertRaises(SystemExit):
            fm_mod.doc_kind(Path("/repo/docs/ansible.md"))


class ReadFrontmatterTest(_TmpRoot):
    def test_flat_adr_files_no_longer_validate(self):
        path = write_doc(self.root, "docs/decisions/0001-x.md", {"id": "ADR-0001", "title": "t", "type": "adr", "status": "accepted"})
        with self.assertRaisesRegex(SystemExit, "lineage directories"):
            fm_mod.read_frontmatter(path)

    def test_type_must_match_location(self):
        path = write_doc(self.root, "docs/projects/p.md", {"id": "PROJ-p", "title": "t", "type": "adr", "status": "done", "summary": "s"})
        with self.assertRaisesRegex(SystemExit, "doesn't match its location"):
            fm_mod.read_frontmatter(path)

    def test_missing_frontmatter_and_required_fields(self):
        path = self.root / "docs/projects/p.md"
        path.parent.mkdir(parents=True)
        path.write_text("# no frontmatter\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "missing frontmatter"):
            fm_mod.read_frontmatter(path)
        no_title = write_doc(self.root, "docs/projects/q.md", {"id": "PROJ-q", "type": "project", "status": "done"})
        with self.assertRaisesRegex(SystemExit, "missing required field 'title'"):
            fm_mod.read_frontmatter(no_title)


class RevisionValidationTest(_TmpRoot):
    def test_every_revision_status_is_accepted(self):
        for n, status in enumerate(sorted(fm_mod.ADR_REVISION_STATUS), start=1):
            extra = {"superseded_by": n + 1} if status == "superseded" else {}
            with self.subTest(status=status):
                path = revision(self.root, "0013-secret-storage", n, status=status, **extra)
                self.assertEqual(fm_mod.read_frontmatter(path)["status"], status)

    def test_rejected_frontmatter(self):
        cases = {
            "id doesn't match directory": {"id": "ADR-0099"},
            "revision doesn't match filename": {"revision": 7},
            "revision is a string": {"revision": "1"},
            "unknown topic": {"topic": "misc"},
            "empty solution": {"solution": "  "},
            "superseded without superseded_by": {"status": "superseded"},
            "superseded_by on a non-superseded revision": {"status": "accepted", "superseded_by": 1},
            "supersedes itself": {"supersedes": 0},
            "supersedes is a bool": {"supersedes": True},
            "narrows is a list": {"narrows": ["ADR-0015"]},
            "related isn't ADR ids": {"related": ["0014"]},
            "former_ids isn't a list": {"former_ids": "ADR-0027"},
        }
        for label, overrides in cases.items():
            with self.subTest(label):
                path = revision(self.root, "0013-secret-storage", 0, **overrides)
                with self.assertRaises(SystemExit):
                    fm_mod.read_frontmatter(path)

    def test_every_topic_is_accepted_including_security_hardening(self):
        for n, topic in enumerate(fm_mod.TOPICS, start=1):
            with self.subTest(topic=topic):
                path = revision(self.root, f"{n:04d}-x", 0, topic=topic)
                self.assertEqual(fm_mod.read_frontmatter(path)["topic"], topic)
        self.assertEqual(fm_mod.TOPICS["security-hardening"], "Security & hardening")

    def test_a_competing_candidate_file_and_its_frontmatter_must_agree(self):
        ok = revision(self.root, "0044-x", 0, letter="a")
        self.assertEqual(fm_mod.read_frontmatter(ok)["candidate"], "a")
        self.assertTrue(ok.name == "revision-000-a.md")
        bad = {
            "lettered file, wrong candidate": revision(self.root, "0045-x", 0, letter="a", candidate="b"),
            "lettered file, no candidate field": None,
            "unlettered file with a candidate field": revision(self.root, "0046-x", 0, candidate="a"),
        }
        no_field = revision(self.root, "0047-x", 0, letter="a")
        text = no_field.read_text(encoding="utf-8").replace("candidate: a\n", "")
        no_field.write_text(text, encoding="utf-8")
        bad["lettered file, no candidate field"] = no_field
        for label, path in bad.items():
            with self.subTest(label), self.assertRaises(SystemExit):
                fm_mod.read_frontmatter(path)

    def test_references_may_name_a_lettered_candidate(self):
        path = revision(self.root, "0044-x", 1, status="accepted", supersedes="0-b")
        self.assertEqual(fm_mod.read_frontmatter(path)["supersedes"], "0-b")
        for label, overrides in {
            "same generation": {"supersedes": "1-a"},
            "malformed": {"supersedes": "b"},
            "uppercase letter": {"supersedes": "0-B"},
            "a quoted bare number": {"supersedes": "0"},
            "negative": {"supersedes": -1},
        }.items():
            with self.subTest(label), self.assertRaises(SystemExit):
                fm_mod.read_frontmatter(revision(self.root, f"01{len(label):02d}-y", 1, **overrides))

    def test_ref_label(self):
        cases = {0: "0", 3: "3", "0-b": "0-b", "12-z": "12-z", "0": None, "b": None, "0-B": None, "01-a": None, -1: None, True: None, None: None, 1.5: None}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(fm_mod.ref_label(value), expected)

    def test_lineage_loads_candidates_in_generation_then_letter_order(self):
        revision(self.root, "0044-x", 1, status="working")
        revision(self.root, "0044-x", 0, letter="b", status="abandoned")
        revision(self.root, "0044-x", 0, letter="a", status="accepted")
        (lineage,) = fm_mod.load_lineages(self.root)
        self.assertEqual([r.label for r in lineage.revisions], ["0-a", "0-b", "1"])
        self.assertEqual([r.number for r in lineage.revisions], [0, 0, 1])
        self.assertEqual(lineage.get("0-b").status, "abandoned")
        self.assertIsNone(lineage.get(0), "a generation with lettered candidates is not addressable by its bare number")
        self.assertEqual(lineage.get(1).label, "1")
        self.assertEqual(lineage.current().label, "0-a")
        self.assertEqual([r.label for r in lineage.pending_successors()], ["1"])

    def test_the_original_is_revision_zero(self):
        path = revision(self.root, "0013-secret-storage", 0)
        self.assertEqual(fm_mod.read_frontmatter(path)["revision"], 0)
        self.assertTrue(path.name == "revision-000.md")
        with self.assertRaises(SystemExit):
            fm_mod.read_frontmatter(revision(self.root, "0014-x", 0, revision=1))

    def test_relations_accepted(self):
        path = revision(self.root, "0013-secret-storage", 1, status="accepted", supersedes=0, narrows="ADR-0015", related=["ADR-0014"], former_ids=["ADR-0027"])
        self.assertEqual(fm_mod.read_frontmatter(path)["narrows"], "ADR-0015")


class ProjectValidationTest(_TmpRoot):
    def test_every_lifecycle_status_is_accepted(self):
        for status in sorted(fm_mod.PROJECT_LIFECYCLE_STATUS):
            with self.subTest(status=status):
                self.assertEqual(fm_mod.read_frontmatter(project(self.root, f"p-{status}", status=status))["status"], status)

    def test_the_pre_lifecycle_statuses_are_rejected(self):
        for status in ("in-progress", "blocked"):
            with self.subTest(status=status), self.assertRaisesRegex(SystemExit, "isn't valid"):
                fm_mod.read_frontmatter(project(self.root, "p", status=status, blocked_reason="x"))

    def test_summary_is_required(self):
        path = write_doc(self.root, "docs/projects/p.md", {"id": "PROJ-p", "title": "p", "type": "project", "status": "done"})
        with self.assertRaisesRegex(SystemExit, "summary"):
            fm_mod.read_frontmatter(path)

    def test_blocked_rules(self):
        self.assertEqual(
            fm_mod.read_frontmatter(project(self.root, "a", status="building", blocked=True, blocked_reason="waiting on hardware"))["blocked"], True
        )
        self.assertEqual(fm_mod.read_frontmatter(project(self.root, "ok", status="building", blocked=False))["blocked"], False)
        bad = {
            "blocked true without reason": {"status": "building", "blocked": True},
            "blocked isn't a bool": {"status": "building", "blocked": "yes"},
        }
        for label, overrides in bad.items():
            with self.subTest(label), self.assertRaises(SystemExit):
                fm_mod.read_frontmatter(project(self.root, "b", **overrides))

    def test_depends_on_shape(self):
        ok = project(self.root, "ok", depends_on=[{"project": "PROJ-other", "reason": "consumes its bootstrap"}])
        self.assertEqual(len(fm_mod.read_frontmatter(ok)["depends_on"]), 1)
        bad = {
            "no reason": [{"project": "PROJ-other"}],
            "blank reason": [{"project": "PROJ-other", "reason": " "}],
            "bad id": [{"project": "other", "reason": "x"}],
            "not a list": {"project": "PROJ-other", "reason": "x"},
        }
        for label, value in bad.items():
            with self.subTest(label), self.assertRaises(SystemExit):
                fm_mod.read_frontmatter(project(self.root, "b", depends_on=value))

    def test_track_and_phase_need_their_parent_label(self):
        ok = project(self.root, "ok", super_project="cd", track="security", phase="bootstrap")
        self.assertEqual(fm_mod.read_frontmatter(ok)["phase"], "bootstrap")
        bad = {
            "track without super_project": {"track": "security"},
            "phase without track": {"super_project": "cd", "phase": "bootstrap"},
            "track isn't a slug": {"super_project": "cd", "track": "Security Track"},
            "phase isn't a slug": {"super_project": "cd", "track": "t", "phase": 1},
        }
        for label, overrides in bad.items():
            with self.subTest(label), self.assertRaises(SystemExit):
                fm_mod.read_frontmatter(project(self.root, "b", **overrides))

    def test_allowed_paths_shape(self):
        ok = project(self.root, "ok", allowed_paths=["src/**", ".github/scripts/doc_*.py", "README.md"])
        self.assertEqual(len(fm_mod.read_frontmatter(ok)["allowed_paths"]), 3)
        bad = {
            "not a list": "src/**",
            "empty list": [],
            "non-string entry": ["src/**", 3],
            "blank entry": ["src/**", " "],
            "absolute": ["/etc/passwd"],
            "parent traversal": ["src/../secrets/**"],
            **{f"blanket {p!r}": [p] for p in sorted(fm_mod.BLANKET_PATHS)},
        }
        for label, value in bad.items():
            with self.subTest(label), self.assertRaises(SystemExit):
                fm_mod.read_frontmatter(project(self.root, "b", allowed_paths=value))

    def test_decision_and_super_project_shape(self):
        self.assertEqual(fm_mod.read_frontmatter(project(self.root, "a", decision="ADR-0013/1", super_project="pull-based-cd"))["decision"], "ADR-0013/1")
        for overrides in ({"decision": "ADR-0013"}, {"decision": ["ADR-0013/1"]}, {"super_project": "Pull Based"}):
            with self.subTest(overrides), self.assertRaises(SystemExit):
                fm_mod.read_frontmatter(project(self.root, "b", **overrides))


class LineageLoadingTest(_TmpRoot):
    def test_load_and_current_revision(self):
        revision(self.root, "0013-secret-storage", 0, status="superseded", superseded_by=1)
        revision(self.root, "0013-secret-storage", 1, status="accepted", supersedes=0)
        revision(self.root, "0013-secret-storage", 2, status="working")
        (lineage,) = fm_mod.load_lineages(self.root)
        self.assertEqual(lineage.id, "ADR-0013")
        self.assertEqual(lineage.current().number, 1)
        self.assertEqual([r.number for r in lineage.pending_successors()], [2])

    def test_current_falls_back_to_newest_pending_then_newest(self):
        revision(self.root, "0001-a", 0, status="working")
        revision(self.root, "0001-a", 1, status="approved")
        revision(self.root, "0002-b", 0, status="abandoned")
        by_id = {lineage.id: lineage for lineage in fm_mod.load_lineages(self.root)}
        self.assertEqual(by_id["ADR-0001"].current().number, 1)
        self.assertEqual(by_id["ADR-0001"].pending_successors(), [])
        self.assertEqual(by_id["ADR-0002"].current().number, 0)

    def test_retired_counts_as_the_live_revision(self):
        revision(self.root, "0001-a", 0, status="retired")
        (lineage,) = fm_mod.load_lineages(self.root)
        self.assertEqual(lineage.current().status, "retired")

    def test_stray_files_and_empty_directories_are_rejected(self):
        revision(self.root, "0001-a", 0)
        (self.root / "docs/decisions/0001-a/README.md").write_text("# manifest\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "only revision-NNN.md"):
            fm_mod.load_lineages(self.root)
        (self.root / "docs/decisions/0001-a/README.md").unlink()
        (self.root / "docs/decisions/0002-empty").mkdir()
        with self.assertRaisesRegex(SystemExit, "no revision files"):
            fm_mod.load_lineages(self.root)

    def test_flat_files_are_not_lineages(self):
        write_doc(self.root, "docs/decisions/0001-flat.md", {"id": "ADR-0001", "title": "t", "type": "adr", "status": "accepted"})
        self.assertEqual(fm_mod.load_lineages(self.root), [])
        self.assertEqual(fm_mod.load_lineages(self.root / "nowhere"), [])
