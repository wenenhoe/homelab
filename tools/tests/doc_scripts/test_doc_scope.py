"""Unit tests for doc_scope.py - the path-scope rule for project work.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import doc_scope as scope
from _doc_fixtures import revision


class GlobTest(unittest.TestCase):
    def test_glob_semantics(self):
        cases = [
            ("src/**", "src/a.py", True),
            ("src/**", "src/x/y/a.py", True),
            ("src/**", "src", False),
            ("src/**", "srcx/a.py", False),
            ("src/**", "other/src/a.py", False),
            ("*.md", "README.md", True),
            ("*.md", "docs/a.md", False),
            ("docs/*.md", "docs/a.md", True),
            ("docs/*.md", "docs/x/a.md", False),
            ("**/test_*.py", "test_a.py", True),
            ("**/test_*.py", "a/b/test_a.py", True),
            ("**/test_*.py", "a/b/atest_a.py", False),
            (".github/scripts/doc_*.py", ".github/scripts/doc_graph.py", True),
            (".github/scripts/doc_*.py", "xgithub/scripts/doc_graph.py", False),
            (".github/scripts/doc_*.py", ".github/scripts/sub/doc_a.py", False),
            ("a?c", "abc", True),
            ("a?c", "a/c", False),
            ("a+b(c).py", "a+b(c).py", True),
            ("a+b(c).py", "aab(c).py", False),
            ("README.md", "README.md", True),
            ("README.md", "docs/README.md", False),
        ]
        for pattern, path, expected in cases:
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(scope.matches(pattern, path), expected)


class DecisionRevisionPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_resolves_plain_and_lettered_labels(self):
        revision(self.root, "0044-trigger", 0, letter="b")
        revision(self.root, "0044-trigger", 1)
        self.assertEqual(scope.decision_revision_path({"decision": "ADR-0044/0-b"}, self.root), "docs/decisions/0044-trigger/revision-000-b.md")
        self.assertEqual(scope.decision_revision_path({"decision": "ADR-0044/1"}, self.root), "docs/decisions/0044-trigger/revision-001.md")

    def test_none_when_absent_or_unresolvable(self):
        self.assertIsNone(scope.decision_revision_path({}, self.root))
        self.assertIsNone(scope.decision_revision_path({"decision": "ADR-0099/0"}, self.root))
        self.assertIsNone(scope.decision_revision_path({"decision": "nonsense"}, self.root))


class ScopeErrorsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.base: dict[str, dict] = {}

    def errors(self, changed: list[str]) -> list[str]:
        return scope.scope_errors(changed, self.base.get, self.root)

    def scoped(self, name: str = "a", paths: list[str] | None = None, **extra) -> str:
        path = f"docs/projects/{name}.md"
        self.base[path] = {"id": f"PROJ-{name}", "allowed_paths": paths if paths is not None else ["src/**"], **extra}
        return path

    def test_a_change_that_touches_no_project_doc_is_never_checked(self):
        self.scoped()
        self.assertEqual(self.errors(["anything/at/all.py", "docs/topic.md"]), [])

    def test_a_project_without_allowed_paths_is_unscoped(self):
        self.base["docs/projects/a.md"] = {"id": "PROJ-a"}
        self.assertEqual(self.errors(["docs/projects/a.md", "anywhere.py"]), [])

    def test_files_inside_the_scope_pass(self):
        doc = self.scoped()
        self.assertEqual(self.errors([doc, "src/a.py", "src/deep/b.py"]), [])

    def test_a_file_outside_the_scope_is_named_with_its_project(self):
        doc = self.scoped()
        errors = self.errors([doc, "src/a.py", "other/b.py"])
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("other/b.py", errors[0])
        self.assertIn("PROJ-a", errors[0])
        self.assertIn("base branch", errors[0])

    def test_the_workflows_own_bookkeeping_is_implicitly_allowed(self):
        doc = self.scoped()
        self.assertEqual(self.errors([doc, "docs/projects/README.md", "docs/projects/sibling.md", "docs/decisions/README.md", "docs/project-planning.md"]), [])

    def test_the_linked_decision_revision_is_implicitly_allowed_but_not_its_neighbours(self):
        revision(self.root, "0001-x", 0)
        revision(self.root, "0001-x", 1)
        doc = self.scoped(decision="ADR-0001/0")
        self.assertEqual(self.errors([doc, "docs/decisions/0001-x/revision-000.md"]), [])
        self.assertEqual(len(self.errors([doc, "docs/decisions/0001-x/revision-001.md"])), 1)

    def test_two_touched_projects_get_the_union_of_their_scopes(self):
        a = self.scoped("a", ["src/**"])
        b = self.scoped("b", ["tools/**"])
        self.assertEqual(self.errors([a, b, "src/x.py", "tools/y.py"]), [])
        errors = self.errors([a, b, "docs/topic.md"])
        self.assertEqual(len(errors), 1)
        self.assertIn("PROJ-a", errors[0])
        self.assertIn("PROJ-b", errors[0])

    def test_only_the_touched_projects_scopes_apply(self):
        a = self.scoped("a", ["src/**"])
        self.scoped("b", ["tools/**"])  # not touched, so not part of the union
        self.assertEqual(len(self.errors([a, "tools/y.py"])), 1)

    def test_a_new_project_doc_has_no_scope_yet(self):
        # no base version: the doc is new in this change, so nothing bounds it
        self.assertEqual(self.errors(["docs/projects/brand-new.md", "anywhere.py"]), [])

    def test_readme_and_template_are_not_project_docs(self):
        self.base["docs/projects/README.md"] = {"id": "x", "allowed_paths": ["src/**"]}
        self.base["docs/projects/TEMPLATE.md"] = {"id": "y", "allowed_paths": ["src/**"]}
        self.assertEqual(self.errors(["docs/projects/README.md", "docs/projects/TEMPLATE.md", "elsewhere.py"]), [])

    def test_duplicates_are_collapsed(self):
        doc = self.scoped()
        self.assertEqual(len(self.errors([doc, "other/b.py", "other/b.py"])), 1)

    def test_a_scope_read_from_the_base_cannot_be_widened_by_the_change_itself(self):
        # The loader returns the BASE frontmatter: even if the change edits allowed_paths
        # to include other/**, the scope in force is still src/**.
        doc = self.scoped(paths=["src/**"])
        self.assertEqual(len(self.errors([doc, "other/b.py"])), 1)
