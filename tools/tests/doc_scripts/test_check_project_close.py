"""Tests for check-project-close.py against a real temporary git repository -
the merge-base, index, and rename behavior is exactly what mocks would get
wrong. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from _doc_fixtures import SCRIPTS, project, revision

_spec = importlib.util.spec_from_file_location("check_project_close", SCRIPTS / "check-project-close.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

LINEAGE = "0001-x"
REVISION = f"docs/decisions/{LINEAGE}/revision-000.md"
CLOSING = "docs/projects/closing.md"
SIBLING = "docs/projects/sibling.md"


class _GitRepo(unittest.TestCase):
    """main holds one approved revision and two projects naming it (`closing`, `sibling`)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.git("init", "-q")
        self.git("checkout", "-q", "-b", "main")
        revision(self.root, LINEAGE, 0, status="approved")
        project(self.root, "closing", status="building", decision="ADR-0001/0")
        project(self.root, "sibling", status="not-started", decision="ADR-0001/0")
        project(self.root, "loner", status="building")
        self.commit("base")

    def git(self, *args: str) -> str:
        cmd = ["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t.t", "-c", "commit.gpgsign=false", *args]
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def branch(self, name: str = "feature") -> None:
        self.git("checkout", "-q", "-b", name)

    def accept(self) -> None:
        path = self.root / REVISION
        path.write_text(path.read_text(encoding="utf-8").replace("status: approved", "status: accepted"), encoding="utf-8")

    def run_cli(self, *args: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([*args, "--root", str(self.root)])
        return code, out.getvalue() + err.getvalue()

    def pr(self) -> tuple[int, str]:
        return self.run_cli("--base", "main", "--head", "feature")


class PullRequestModeTest(_GitRepo):
    def test_deleting_a_project_while_a_sibling_remains_passes(self):
        self.branch()
        self.git("rm", "-q", CLOSING)
        self.commit("close, not last")
        code, out = self.pr()
        self.assertEqual(code, 0, out)

    def test_deleting_the_last_project_naming_an_unaccepted_revision_fails(self):
        self.branch()
        self.git("rm", "-q", CLOSING, SIBLING)
        self.commit("close both")
        code, out = self.pr()
        self.assertEqual(code, 1, out)
        self.assertIn(CLOSING, out)
        self.assertIn(SIBLING, out)
        self.assertIn("ADR-0001/0", out)

    def test_accepting_the_revision_in_the_same_change_passes(self):
        self.branch()
        self.git("rm", "-q", CLOSING, SIBLING)
        self.accept()
        self.commit("close both and accept")
        code, out = self.pr()
        self.assertEqual(code, 0, out)

    def test_a_successor_added_in_the_same_change_passes(self):
        self.branch()
        self.git("rm", "-q", CLOSING, SIBLING)
        project(self.root, "remainder", status="not-started", decision="ADR-0001/0")
        self.commit("close both, carry the rest into a successor")
        code, out = self.pr()
        self.assertEqual(code, 0, out)

    def test_a_change_that_deletes_no_project_doc_is_not_checked(self):
        self.branch()
        (self.root / CLOSING).write_text((self.root / CLOSING).read_text(encoding="utf-8") + "\nmore\n", encoding="utf-8")
        self.commit("edit only")
        code, out = self.pr()
        self.assertEqual(code, 0, out)
        self.assertIn("nothing to close-check", out)

    def test_deleting_a_project_with_no_decision_passes(self):
        self.branch()
        self.git("rm", "-q", "docs/projects/loner.md")
        self.commit("close loner")
        self.assertEqual(self.pr()[0], 0)

    def test_a_renamed_project_doc_keeps_the_revision_named(self):
        self.branch()
        self.git("rm", "-q", SIBLING)
        self.git("mv", CLOSING, "docs/projects/renamed.md")
        self.commit("rename one, close the other")
        code, out = self.pr()
        self.assertEqual(code, 0, out)

    def test_a_project_main_added_after_the_branch_point_is_not_a_deletion_by_the_branch(self):
        self.branch()
        (self.root / "notes.txt").write_text("x\n", encoding="utf-8")
        self.commit("unrelated work")
        self.git("checkout", "-q", "main")
        revision(self.root, "0002-y", 0, status="approved")
        project(self.root, "late", status="not-started", decision="ADR-0002/0")
        self.commit("main moves on")  # a diff from main's tip would show the branch as deleting late.md
        code, out = self.pr()
        self.assertEqual(code, 0, out)

    def test_a_result_whose_docs_do_not_parse_fails_closed(self):
        self.branch()
        self.git("rm", "-q", CLOSING)
        (self.root / SIBLING).write_text("no frontmatter here\n", encoding="utf-8")
        self.commit("close one, break another")
        code, out = self.pr()
        self.assertEqual(code, 1, out)
        self.assertIn("missing frontmatter", out)
        self.assertNotIn(str(self.root), out)


class StagedModeTest(_GitRepo):
    def test_a_staged_deletion_of_the_last_project_fails(self):
        self.git("rm", "-q", CLOSING, SIBLING)
        code, out = self.run_cli("--staged")
        self.assertEqual(code, 1, out)
        self.assertIn(CLOSING, out)

    def test_a_staged_deletion_with_a_staged_acceptance_passes(self):
        self.git("rm", "-q", CLOSING, SIBLING)
        self.accept()
        self.git("add", REVISION)
        code, out = self.run_cli("--staged")
        self.assertEqual(code, 0, out)

    def test_an_unstaged_acceptance_does_not_count(self):
        self.git("rm", "-q", CLOSING, SIBLING)
        self.accept()  # edited but not staged: not part of this commit
        code, out = self.run_cli("--staged")
        self.assertEqual(code, 1, out)

    def test_a_staged_deletion_while_a_sibling_remains_passes(self):
        self.git("rm", "-q", CLOSING)
        self.assertEqual(self.run_cli("--staged")[0], 0)

    def test_nothing_staged_passes(self):
        code, out = self.run_cli("--staged")
        self.assertEqual(code, 0, out)
        self.assertIn("nothing to close-check", out)

    def test_a_repository_with_no_commits_yet_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            fresh = Path(d)
            subprocess.run(["git", "-C", str(fresh), "init", "-q"], check=True)
            project(fresh, "p", status="building")
            subprocess.run(["git", "-C", str(fresh), "add", "-A"], check=True)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["--staged", "--root", str(fresh)])
            self.assertEqual(code, 0, out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
