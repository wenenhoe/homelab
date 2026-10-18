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


class TestRevisionPath:
    @pytest.mark.parametrize("ref", [None, 1, ["ADR-0001/0"]], ids=["none", "int", "list"])
    def test_none_for_a_reference_that_is_not_a_string(self, root, ref):
        revision(root, "0001-x", 0)
        assert scope.revision_path(ref, root) is None


class TestLifecyclePaths:
    X0 = "docs/decisions/0001-x/revision-000.md"
    X1 = "docs/decisions/0001-x/revision-001.md"
    Y0 = "docs/decisions/0002-y/revision-000.md"
    Y1 = "docs/decisions/0002-y/revision-001.md"

    @pytest.fixture
    def base(self) -> dict[str, dict]:
        return {}

    def test_a_decision_that_supersedes_nothing_exempts_only_itself(self, root, base):
        revision(root, "0001-x", 0)
        assert scope.lifecycle_paths({"decision": "ADR-0001/0"}, base.get, root) == {self.X0: "decision"}

    def test_the_revision_a_decision_supersedes_is_exempt_too(self, root, base):
        revision(root, "0001-x", 0)
        revision(root, "0001-x", 1)
        base[self.X1] = {"supersedes": 0}
        assert scope.lifecycle_paths({"decision": "ADR-0001/1"}, base.get, root) == {self.X1: "decision", self.X0: "superseded"}

    def test_each_also_implements_revision_and_its_predecessor_is_exempt(self, root, base):
        revision(root, "0001-x", 0)
        revision(root, "0002-y", 0)
        revision(root, "0002-y", 1)
        base[self.Y1] = {"supersedes": 0}
        found = scope.lifecycle_paths({"decision": "ADR-0001/0", "also_implements": ["ADR-0002/1"]}, base.get, root)
        assert found == {self.X0: "decision", self.Y1: "also_implements", self.Y0: "superseded"}

    def test_a_lettered_predecessor_is_found(self, root, base):
        revision(root, "0001-x", 0, letter="b")
        revision(root, "0001-x", 1)
        base[self.X1] = {"supersedes": "0-b"}
        found = scope.lifecycle_paths({"decision": "ADR-0001/1"}, base.get, root)
        assert found == {self.X1: "decision", "docs/decisions/0001-x/revision-000-b.md": "superseded"}

    def test_a_predecessor_with_no_file_is_left_out(self, root, base):
        revision(root, "0001-x", 1)
        base[self.X1] = {"supersedes": 0}
        assert scope.lifecycle_paths({"decision": "ADR-0001/1"}, base.get, root) == {self.X1: "decision"}

    def test_a_reference_to_a_revision_that_does_not_exist_exempts_nothing(self, root, base):
        assert scope.lifecycle_paths({"decision": "ADR-0099/0", "also_implements": ["ADR-0098/0"]}, base.get, root) == {}

    def test_supersedes_is_read_from_the_base_not_from_the_tree(self, root, base):
        revision(root, "0001-x", 0)
        revision(root, "0001-x", 1, supersedes=0)  # the tree says it; the base does not
        assert scope.lifecycle_paths({"decision": "ADR-0001/1"}, base.get, root) == {self.X1: "decision"}


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

    def test_the_revision_a_decision_supersedes_is_implicitly_allowed(self, root, base, scoped, errors):
        revision(root, "0001-x", 0)
        revision(root, "0001-x", 1)
        doc = scoped(decision="ADR-0001/1")
        base["docs/decisions/0001-x/revision-001.md"] = {"supersedes": 0}
        assert errors([doc, "docs/decisions/0001-x/revision-000.md", "docs/decisions/0001-x/revision-001.md"]) == []

    def test_a_revision_the_decision_does_not_supersede_stays_outside(self, root, base, scoped, errors):
        for number in range(3):
            revision(root, "0001-x", number)
        doc = scoped(decision="ADR-0001/1")
        base["docs/decisions/0001-x/revision-001.md"] = {"supersedes": 0}
        found = errors([doc, "docs/decisions/0001-x/revision-002.md"])
        assert len(found) == 1, found
        assert "revision-002.md" in found[0]

    def test_also_implements_revisions_and_their_predecessors_are_implicitly_allowed(self, root, base, scoped, errors):
        revision(root, "0001-x", 0)
        revision(root, "0002-y", 0)
        revision(root, "0002-y", 1)
        doc = scoped(decision="ADR-0001/0", also_implements=["ADR-0002/1"])
        base["docs/decisions/0002-y/revision-001.md"] = {"supersedes": 0}
        assert errors([doc, "docs/decisions/0002-y/revision-000.md", "docs/decisions/0002-y/revision-001.md"]) == []

    def test_a_change_cannot_exempt_a_revision_by_adding_the_supersedes_that_names_it(self, root, scoped, errors):
        revision(root, "0001-x", 0)
        revision(root, "0001-x", 1, supersedes=0)  # added by the change; the base revision has none
        doc = scoped(decision="ADR-0001/1")
        found = errors([doc, "docs/decisions/0001-x/revision-000.md"])
        assert len(found) == 1, found
        assert "revision-000.md" in found[0]

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


PLAN = (
    "## Execution plan\n\n| # | Stage | Status | Exit condition |\n| :-: | :--- | :--- | :--- |\n"
    "| 1 | First | {status} | {exit} |\n{more}\n## Risks\n\n{prose}\n"
)


def doc(status: str = "Not started", exit: str = "built", prose: str = "none", front: str = "id: PROJ-a", more: str = "") -> str:
    return f"---\n{front}\n---\n\n# A\n\n" + PLAN.format(status=status, exit=exit, prose=prose, more=more)


class TestIsWorked:
    def test_prose_and_exit_condition_wording_are_not_work(self):
        assert not scope.is_worked(doc(), doc(prose="reworded", exit="built, linked"))

    def test_a_stage_status_change_is_work(self):
        assert scope.is_worked(doc(), doc(status="In progress"))

    def test_a_frontmatter_change_is_work(self):
        assert scope.is_worked(doc(), doc(front="id: PROJ-a\nstatus: building"))

    def test_a_new_stage_row_is_work(self):
        assert scope.is_worked(doc(), doc(more="| 2 | Second | Not started | x |\n"))

    def test_a_deleted_doc_is_work(self):
        assert scope.is_worked(doc(), None)

    def test_a_doc_with_no_plan_table_compares_on_frontmatter_alone(self):
        assert not scope.is_worked("---\nid: PROJ-a\n---\n\nbody\n", "---\nid: PROJ-a\n---\n\nbody, edited\n")


class TestWorkedGatesScope:
    def test_a_touched_but_unworked_project_binds_nothing(self, root):
        base = {"docs/projects/a.md": {"id": "PROJ-a", "allowed_paths": ["src/**"]}}
        changed = ["docs/projects/a.md", "elsewhere/x.py"]
        assert scope.scope_errors(changed, base.get, root, worked=lambda path: False) == []
        assert scope.scope_errors(changed, base.get, root, worked=lambda path: True) != []
