"""Tests for check-project-scope.py against a real temporary git repository -
the merge-base, staged-file, and path-quoting behavior is exactly what mocks
would get wrong. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from _doc_fixtures import SCRIPTS

_spec = importlib.util.spec_from_file_location("check_project_scope", SCRIPTS / "check-project-scope.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

PROJECT = "docs/projects/p.md"


def project_doc(paths: list[str], decision: str | None = None) -> str:
    lines = ["---", "id: PROJ-p", "title: p", "type: project", "status: building", "summary: s", "allowed_paths:", *[f"  - '{p}'" for p in paths]]
    if decision:
        lines.append(f"decision: {decision}")
    return "\n".join([*lines, "---", "", "# p", ""])


class _GitRepo(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.git("init", "-q")
        self.git("checkout", "-q", "-b", "main")
        self.write(PROJECT, project_doc(["src/**"]))
        self.write("src/a.py", "a = 1\n")
        self.write("other/b.py", "b = 1\n")
        self.commit("base")

    def git(self, *args: str) -> str:
        cmd = ["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t.t", "-c", "commit.gpgsign=false", *args]
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def branch(self, name: str = "feature") -> None:
        self.git("checkout", "-q", "-b", name)

    def run_cli(self, *args: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([*args, "--root", str(self.root)])
        return code, out.getvalue() + err.getvalue()

    def pr(self) -> tuple[int, str]:
        return self.run_cli("--base", "main", "--head", "feature")


class PullRequestModeTest(_GitRepo):
    def test_a_change_inside_the_scope_passes(self):
        self.branch()
        self.write("src/a.py", "a = 2\n")
        self.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, stage 1 started"))
        self.commit("work")
        code, out = self.pr()
        self.assertEqual(code, 0, out)

    def test_a_change_outside_the_scope_fails_and_names_the_file(self):
        self.branch()
        self.write("other/b.py", "b = 2\n")
        self.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, stage 1 started"))
        self.commit("stray")
        code, out = self.pr()
        self.assertEqual(code, 1)
        self.assertIn("other/b.py", out)
        self.assertNotIn("src/a.py", out)

    def test_a_change_that_touches_no_project_doc_is_not_checked(self):
        self.branch()
        self.write("other/b.py", "b = 2\n")
        self.commit("unrelated fix")
        code, out = self.pr()
        self.assertEqual(code, 0, out)
        self.assertIn("nothing to scope", out)

    def test_a_change_cannot_widen_its_own_scope(self):
        self.branch()
        self.write(PROJECT, project_doc(["src/**", "other/**"]))
        self.write("other/b.py", "b = 2\n")
        self.commit("widen and use it in one change")
        code, out = self.pr()
        self.assertEqual(code, 1, out)
        self.assertIn("other/b.py", out)

    def test_widening_on_its_own_is_fine(self):
        self.branch()
        self.write(PROJECT, project_doc(["src/**", "other/**"]))
        self.commit("widen")
        code, out = self.pr()
        self.assertEqual(code, 0, out)

    def test_a_branch_that_is_behind_is_not_blamed_for_mains_newer_commits(self):
        self.branch()
        self.write("src/a.py", "a = 2\n")
        self.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, started"))
        self.commit("work")
        self.git("checkout", "-q", "main")
        self.write("other/c.py", "c = 1\n")  # main moves on, outside the scope
        self.commit("someone else's change to main")
        code, out = self.pr()  # a two-dot diff of main against feature would report other/c.py
        self.assertEqual(code, 0, out)

    def test_a_brand_new_project_doc_has_no_scope_yet(self):
        self.branch()
        self.write("docs/projects/new.md", project_doc(["only/here/**"]))
        self.write("anything/goes.py", "x = 1\n")
        self.commit("new project and its first work")
        code, out = self.pr()
        self.assertEqual(code, 0, out)

    def test_renames_and_deletions_count_as_touching_both_paths(self):
        self.branch()
        self.git("mv", "src/a.py", "other/a.py")  # leaves the scope
        self.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, moved"))
        self.commit("move out")
        code, out = self.pr()
        self.assertEqual(code, 1)
        self.assertIn("other/a.py", out)
        self.git("checkout", "-q", "main")
        self.git("branch", "-q", "-D", "feature")
        self.branch()
        self.git("rm", "-q", "other/b.py")
        self.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, deleted"))
        self.commit("delete outside")
        code, out = self.pr()
        self.assertEqual(code, 1)
        self.assertIn("other/b.py", out)

    def test_moving_a_file_into_the_scope_still_counts_as_touching_where_it_came_from(self):
        self.branch()
        self.git("mv", "other/b.py", "src/b.py")  # rename detection would show only the in-scope destination
        self.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, moved in"))
        self.commit("move in")
        code, out = self.pr()
        self.assertEqual(code, 1, out)
        self.assertIn("other/b.py", out)

    def test_paths_with_spaces_and_unicode_are_reported_intact(self):
        self.branch()
        self.write("other/we ird é.py", "x = 1\n")
        self.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, odd"))
        self.commit("odd name")
        code, out = self.pr()
        self.assertEqual(code, 1)
        self.assertIn("other/we ird é.py", out)

    def test_the_linked_decision_revision_may_change(self):
        self.write(PROJECT, project_doc(["src/**"], decision="ADR-0001/0"))
        self.write("docs/decisions/0001-x/revision-000.md", "adr\n")
        self.write("docs/decisions/0001-x/revision-001.md", "adr\n")
        self.commit("link a decision")
        self.branch()
        self.write("docs/decisions/0001-x/revision-000.md", "adr, edited\n")
        self.write(PROJECT, project_doc(["src/**"], decision="ADR-0001/0").replace("# p", "# p, x"))
        self.commit("the permitted ADR edit")
        self.assertEqual(self.pr()[0], 0)
        self.write("docs/decisions/0001-x/revision-001.md", "adr, edited\n")
        self.commit("a neighbour, not the linked one")
        self.assertEqual(self.pr()[0], 1)


class StagedModeTest(_GitRepo):
    def test_staged_changes_outside_the_scope_fail(self):
        self.write("other/b.py", "b = 2\n")
        self.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, started"))
        self.git("add", "-A")
        code, out = self.run_cli("--staged")
        self.assertEqual(code, 1)
        self.assertIn("other/b.py", out)

    def test_staged_changes_inside_the_scope_pass(self):
        self.write("src/a.py", "a = 2\n")
        self.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, started"))
        self.git("add", "-A")
        self.assertEqual(self.run_cli("--staged")[0], 0)

    def test_unstaged_changes_are_ignored(self):
        self.write(PROJECT, project_doc(["src/**"]).replace("# p", "# p, started"))
        self.git("add", "-A")
        self.write("other/b.py", "b = 2\n")  # edited but not staged: not part of this commit
        self.assertEqual(self.run_cli("--staged")[0], 0)

    def test_nothing_staged_passes(self):
        code, out = self.run_cli("--staged")
        self.assertEqual(code, 0, out)

    def test_a_repository_with_no_commits_yet_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            fresh = Path(d)
            subprocess.run(["git", "-C", str(fresh), "init", "-q"], check=True)
            (fresh / "docs/projects").mkdir(parents=True)
            (fresh / "docs/projects/p.md").write_text(project_doc(["src/**"]), encoding="utf-8")
            subprocess.run(["git", "-C", str(fresh), "add", "-A"], check=True)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["--staged", "--root", str(fresh)])
            self.assertEqual(code, 0, out.getvalue() + err.getvalue())
