"""Sorting a change into a category and a group is a pure function of its paths and title."""

from __future__ import annotations

import pytest
from _progress_fixtures import decision_path, project_path
from progress_log import classify


class TestBucket:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            pytest.param("docs/topics/x.md", "docs/", id="docs"),
            pytest.param("ansible/roles/gatus/tasks/main.yaml", "ansible/roles/", id="role"),
            pytest.param("ansible/playbooks/site.yaml", "ansible/ (playbooks, inventory)", id="playbook"),
            pytest.param("docker/gatus/compose.yaml", "docker/", id="docker"),
            pytest.param("tools/ci/proc.py", "tools/", id="tools"),
            pytest.param(".github/workflows/a.yml", ".github/ and repo config", id="github"),
            pytest.param("pyproject.toml", ".github/ and repo config", id="repo-config-file"),
            pytest.param("tofu/main.tf", "tofu/", id="other-directory"),
            pytest.param("LICENSE", "Root files", id="root-file"),
        ],
    )
    def test_names_the_area_by_its_path(self, path, expected):
        assert classify.bucket(path) == expected


class TestCategory:
    @pytest.mark.parametrize(
        ("paths", "bot", "expected"),
        [
            pytest.param(["docker/a/compose.yaml"], True, "dep", id="bot-wins"),
            pytest.param(["docs/a.md", "tools/x.py"], False, "built", id="any-code-is-built"),
            pytest.param([project_path("a"), "docs/projects/README.md"], False, "scope", id="only-project-docs"),
            pytest.param(["docs/topics/a.md", project_path("a")], False, "planned", id="other-docs"),
            pytest.param(["docs/projects/README.md", "docs/project-planning.md"], False, "planned", id="only-generated-views"),
        ],
    )
    def test_follows_the_paths_touched(self, paths, bot, expected):
        assert classify.category(paths, bot) == expected


class TestGroup:
    def test_a_bot_change_is_a_dependency_update(self):
        assert classify.group(["docker/a/compose.yaml"], True, "bump a", []) == classify.DEPENDENCY_UPDATES

    def test_one_project_doc_names_the_project(self):
        assert classify.group([project_path("gatus-rollout")], False, "tidy", []) == "Project: gatus-rollout"

    def test_a_state_change_picks_the_project_among_several(self):
        events = [["project", "beta", "building → done"]]
        paths = [project_path("alpha"), project_path("beta")]
        assert classify.group(paths, False, "unrelated words", events) == "Project: beta"

    def test_the_title_picks_the_project_when_no_state_changed(self):
        paths = [project_path("alpha"), project_path("vm-provisioning")]
        assert classify.group(paths, False, "scope vm provisioning", []) == "Project: vm-provisioning"

    def test_several_projects_with_no_evidence_are_planning(self):
        paths = [project_path("alpha"), project_path("beta")]
        assert classify.group(paths, False, "reshuffle", []) == classify.SEVERAL_PROJECTS

    def test_decision_files_alone_are_decisions(self):
        paths = [decision_path("0001", "x"), "docs/decisions/README.md"]
        assert classify.group(paths, False, "add adr", []) == classify.DECISIONS

    def test_code_outweighs_docs_in_naming_the_area(self):
        paths = ["docs/topics/a.md", "docs/topics/b.md", "docker/a/compose.yaml"]
        assert classify.group(paths, False, "add a", []) == "docker/"

    def test_the_commonest_code_area_wins(self):
        paths = ["tools/a.py", "tools/b.py", "docker/a/compose.yaml"]
        assert classify.group(paths, False, "change", []) == "tools/"


class TestNormaliseType:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [pytest.param("feat", "feat", id="known"), pytest.param("hotfix", "fix", id="alias"), pytest.param("whatever", "other", id="unknown")],
    )
    def test_maps_to_a_known_type_or_other(self, raw, expected):
        assert classify.normalise_type(raw) == expected
