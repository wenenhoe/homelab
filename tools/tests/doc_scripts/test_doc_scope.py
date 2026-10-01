"""Unit tests for doc_scope.py - the path-scope rule for project work.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
from _doc_fixtures import revision
from doc_scripts import doc_scope as scope


class TestGlob:
    @pytest.mark.parametrize(
        ("pattern", "path", "expected"),
        [
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
            ("tools/doc_scripts/doc_*.py", "tools/doc_scripts/doc_graph.py", True),
            ("tools/doc_scripts/doc_*.py", "xtools/doc_scripts/doc_graph.py", False),
            ("tools/doc_scripts/doc_*.py", "tools/doc_scripts/sub/doc_a.py", False),
            ("a?c", "abc", True),
            ("a?c", "a/c", False),
            ("a+b(c).py", "a+b(c).py", True),
            ("a+b(c).py", "aab(c).py", False),
            ("README.md", "README.md", True),
            ("README.md", "docs/README.md", False),
        ],
    )
    def test_glob_semantics(self, pattern, path, expected):
        assert scope.matches(pattern, path) == expected


class TestDecisionRevisionPath:
    def test_resolves_plain_and_lettered_labels(self, root):
        revision(root, "0044-trigger", 0, letter="b")
        revision(root, "0044-trigger", 1)
        assert scope.decision_revision_path({"decision": "ADR-0044/0-b"}, root) == "docs/decisions/0044-trigger/revision-000-b.md"
        assert scope.decision_revision_path({"decision": "ADR-0044/1"}, root) == "docs/decisions/0044-trigger/revision-001.md"

    def test_none_when_absent_or_unresolvable(self, root):
        assert scope.decision_revision_path({}, root) is None
        assert scope.decision_revision_path({"decision": "ADR-0099/0"}, root) is None
        assert scope.decision_revision_path({"decision": "nonsense"}, root) is None


class TestScopeErrors:
    @pytest.fixture
    def base(self) -> dict[str, dict]:
        return {}

    @pytest.fixture
    def errors(self, base, root):
        return lambda changed: scope.scope_errors(changed, base.get, root)

    @pytest.fixture
    def scoped(self, base):
        def _scoped(name: str = "a", paths: list[str] | None = None, **extra) -> str:
            path = f"docs/projects/{name}.md"
            base[path] = {"id": f"PROJ-{name}", "allowed_paths": paths if paths is not None else ["src/**"], **extra}
            return path

        return _scoped

    def test_a_change_that_touches_no_project_doc_is_never_checked(self, scoped, errors):
        scoped()
        assert errors(["anything/at/all.py", "docs/topic.md"]) == []

    def test_a_project_without_allowed_paths_is_unscoped(self, base, errors):
        base["docs/projects/a.md"] = {"id": "PROJ-a"}
        assert errors(["docs/projects/a.md", "anywhere.py"]) == []

    def test_files_inside_the_scope_pass(self, scoped, errors):
        doc = scoped()
        assert errors([doc, "src/a.py", "src/deep/b.py"]) == []

    def test_a_file_outside_the_scope_is_named_with_its_project(self, scoped, errors):
        doc = scoped()
        found = errors([doc, "src/a.py", "other/b.py"])
        assert len(found) == 1, found
        assert "other/b.py" in found[0]
        assert "PROJ-a" in found[0]
        assert "base branch" in found[0]

    def test_the_workflows_own_bookkeeping_is_implicitly_allowed(self, scoped, errors):
        doc = scoped()
        assert errors([doc, "docs/projects/README.md", "docs/projects/sibling.md", "docs/decisions/README.md", "docs/project-planning.md"]) == []

    def test_the_linked_decision_revision_is_implicitly_allowed_but_not_its_neighbours(self, root, scoped, errors):
        revision(root, "0001-x", 0)
        revision(root, "0001-x", 1)
        doc = scoped(decision="ADR-0001/0")
        assert errors([doc, "docs/decisions/0001-x/revision-000.md"]) == []
        assert len(errors([doc, "docs/decisions/0001-x/revision-001.md"])) == 1

    def test_two_touched_projects_get_the_union_of_their_scopes(self, scoped, errors):
        a = scoped("a", ["src/**"])
        b = scoped("b", ["tools/**"])
        assert errors([a, b, "src/x.py", "tools/y.py"]) == []
        found = errors([a, b, "docs/topic.md"])
        assert len(found) == 1
        assert "PROJ-a" in found[0]
        assert "PROJ-b" in found[0]

    def test_only_the_touched_projects_scopes_apply(self, scoped, errors):
        a = scoped("a", ["src/**"])
        scoped("b", ["tools/**"])  # not touched, so not part of the union
        assert len(errors([a, "tools/y.py"])) == 1

    def test_a_new_project_doc_has_no_scope_yet(self, errors):
        # no base version: the doc is new in this change, so nothing bounds it
        assert errors(["docs/projects/brand-new.md", "anywhere.py"]) == []

    def test_readme_and_template_are_not_project_docs(self, base, errors):
        base["docs/projects/README.md"] = {"id": "x", "allowed_paths": ["src/**"]}
        base["docs/projects/TEMPLATE.md"] = {"id": "y", "allowed_paths": ["src/**"]}
        assert errors(["docs/projects/README.md", "docs/projects/TEMPLATE.md", "elsewhere.py"]) == []

    def test_duplicates_are_collapsed(self, scoped, errors):
        doc = scoped()
        assert len(errors([doc, "other/b.py", "other/b.py"])) == 1

    def test_a_scope_read_from_the_base_cannot_be_widened_by_the_change_itself(self, scoped, errors):
        # The loader returns the BASE frontmatter: even if the change edits allowed_paths
        # to include other/**, the scope in force is still src/**.
        doc = scoped(paths=["src/**"])
        assert len(errors([doc, "other/b.py"])) == 1
