"""Tests for ci.scope.compose_apps.

Function-level cases build a scratch docker/ tree; the CLI cases run
`main` against a real git history; the last class checks invariants of the
actual repo. The syntax check goes through a stub runner, so nothing needs
docker.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from ci.scope import compose_apps as ca

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class Tree:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, rel: str, text: str = "x\n") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


class Repo(Tree):
    """The tree as a git repository, and `main` run against it."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(root)
        self.monkeypatch = monkeypatch
        self.out = root / "out.txt"
        self.base = ""

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, env={**os.environ, **GIT_ENV}, capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def main(self, *argv: str, run=None) -> int:
        self.monkeypatch.setattr(ca, "REPO_ROOT", self.root)
        self.monkeypatch.setenv("GITHUB_OUTPUT", str(self.out))
        return ca.main(list(argv), run) if run else ca.main(list(argv))


def apps(tree: Tree, *changed: str) -> list[str]:
    return ca.changed_apps(tree.root, list(changed))


@pytest.fixture
def tree(root):
    tree = Tree(root)
    tree.write(ca.EXCLUSIONS_FILE, "# excluded\n\ncaddy\n  seaweedfs  \n# tinyauth is only mentioned in a comment\n")
    for app in ("lldap", "wastebin", "caddy", "dashy", "plain", "seaweedfs"):
        tree.write(f"docker/{app}/compose.yaml{'.j2' if app == 'lldap' else ''}")
    tree.write("docker/lldap/configs/env.j2")
    tree.write("docker/lldap/scripts/run.sh")
    tree.write("docker/wastebin/Dockerfile")
    tree.write("docker/caddy/Dockerfile")
    tree.write("docker/caddy/configs/env.j2")
    tree.write("docker/dashy/configs/conf.yaml.j2")
    tree.write("docker/openbao/policies/controller.hcl")
    tree.write("docker/molecule-dind/Dockerfile")
    tree.write("docs/topics/engineering/ci/pipeline.md")
    return tree


class TestExclusion:
    def test_comments_blank_lines_and_whitespace_are_ignored(self, tree):
        assert ca.load_exclusions(tree.root) == {"caddy", "seaweedfs"}

    def test_missing_file_is_an_error(self, tree):
        (tree.root / ca.EXCLUSIONS_FILE).unlink()
        with pytest.raises(ca.ComposeAppsError, match="can't read"):
            ca.load_exclusions(tree.root)


class TestAllApps:
    def test_lists_compose_apps_sorted_minus_excluded(self, tree):
        assert ca.all_apps(tree.root) == ["dashy", "lldap", "plain", "wastebin"]

    def test_directory_without_a_compose_file_is_not_an_app(self, tree):
        assert "openbao" not in ca.all_apps(tree.root)
        assert "molecule-dind" not in ca.all_apps(tree.root)

    def test_templated_compose_file_counts(self, tree):
        assert "lldap" in ca.all_apps(tree.root)


class TestChangedApps:
    @pytest.mark.parametrize(
        ("changed", "app"),
        [
            pytest.param("docker/lldap/configs/env.j2", "lldap", id="configs"),
            pytest.param("docker/lldap/configs/sub/dir/x.j2", "lldap", id="nested-configs"),
            pytest.param("docker/lldap/scripts/run.sh", "lldap", id="scripts"),
            pytest.param("docker/lldap/compose.yaml.j2", "lldap", id="templated-compose"),
            pytest.param("docker/plain/compose.yaml", "plain", id="plain-compose"),
            pytest.param("docker/wastebin/Dockerfile", "wastebin", id="dockerfile"),
        ],
    )
    def test_a_change_to_a_file_the_app_ships_queues_the_app(self, tree, changed, app):
        assert apps(tree, changed) == [app]

    @pytest.mark.parametrize(
        "changed",
        [
            pytest.param(("docker/caddy/configs/env.j2", "docker/caddy/Dockerfile", "docker/caddy/compose.yaml"), id="excluded-app"),
            pytest.param(("docker/molecule-dind/Dockerfile", "docker/openbao/configs/x.j2"), id="directory-without-a-compose-file"),
            pytest.param(
                ("docker/openbao/policies/controller.hcl", "docker/lldap/README.md", "docs/topics/engineering/ci/pipeline.md"),
                id="files-outside-configs-scripts-compose-and-dockerfile",
            ),
            pytest.param(("docker/lldap/configs",), id="bare-configs-directory-name"),
            pytest.param(("docker/plain/compose.yaml.bak", "docker/plain/docker-compose.yaml", "docker/plain/sub/Dockerfile"), id="similarly-named-file"),
        ],
    )
    def test_a_change_that_belongs_to_no_app_queues_nothing(self, tree, changed):
        assert apps(tree, *changed) == []

    def test_deleting_only_a_config_still_queues_the_app(self, tree):
        (tree.root / "docker/lldap/configs/env.j2").unlink()
        assert apps(tree, "docker/lldap/configs/env.j2") == ["lldap"]

    def test_deleting_the_whole_app_queues_nothing(self, tree):
        shutil.rmtree(tree.root / "docker/dashy")
        assert apps(tree, "docker/dashy/compose.yaml", "docker/dashy/configs/conf.yaml.j2") == []

    def test_two_apps_are_sorted_and_deduplicated(self, tree):
        assert apps(tree, "docker/lldap/configs/env.j2", "docker/dashy/configs/conf.yaml.j2", "docker/lldap/scripts/run.sh") == ["dashy", "lldap"]


class TestChangedDockerfiles:
    def test_excluded_and_composeless_apps_are_included(self, tree):
        assert ca.changed_dockerfiles(tree.root, ["docker/caddy/Dockerfile", "docker/molecule-dind/Dockerfile", "docker/wastebin/Dockerfile"]) == [
            "caddy",
            "molecule-dind",
            "wastebin",
        ]

    def test_only_the_dockerfile_itself_counts(self, tree):
        assert ca.changed_dockerfiles(tree.root, ["docker/caddy/compose.yaml", "docker/lldap/configs/env.j2", "docker/caddy/sub/Dockerfile"]) == []

    def test_deleted_dockerfile_is_not_queued(self, tree):
        (tree.root / "docker/wastebin/Dockerfile").unlink()
        assert ca.changed_dockerfiles(tree.root, ["docker/wastebin/Dockerfile"]) == []

    def test_a_tool_image_outside_docker_is_queued_by_its_registry_key(self, tree):
        tree.write("tools/coderabbit-review/Dockerfile")
        assert ca.changed_dockerfiles(tree.root, ["tools/coderabbit-review/Dockerfile", "docker/caddy/Dockerfile"]) == ["caddy", "coderabbit-review"]

    def test_a_tool_image_is_never_a_boot_test_app(self, tree):
        tree.write("tools/coderabbit-review/Dockerfile")
        assert apps(tree, "tools/coderabbit-review/Dockerfile") == []

    def test_other_files_under_a_tool_image_dir_do_not_queue_it(self, tree):
        tree.write("tools/coderabbit-review/Dockerfile")
        assert ca.changed_dockerfiles(tree.root, ["tools/coderabbit-review/coderabbit-review.sh", "tools/coderabbit-review/sub/Dockerfile"]) == []

    def test_deleted_tool_image_dockerfile_is_not_queued(self, tree):
        assert ca.changed_dockerfiles(tree.root, ["tools/coderabbit-review/Dockerfile"]) == []

    def test_a_docker_dockerfile_with_no_registry_entry_is_still_queued(self, tree):
        tree.write("docker/newapp/Dockerfile")
        assert ca.changed_dockerfiles(tree.root, ["docker/newapp/Dockerfile"]) == ["newapp"]


class TestExcludedComposeFiles:
    def test_changed_compose_yaml_of_an_excluded_app_is_listed(self, tree):
        tree.write("docker/caddy/compose.override.yaml")
        assert ca.excluded_compose_files(tree.root, ["docker/caddy/compose.yaml", "docker/caddy/compose.override.yaml", "docker/seaweedfs/compose.yaml"]) == [
            "docker/caddy/compose.override.yaml",
            "docker/caddy/compose.yaml",
            "docker/seaweedfs/compose.yaml",
        ]

    def test_non_excluded_apps_and_templates_and_other_files_are_not(self, tree):
        tree.write("docker/seaweedfs/compose.yaml.j2")
        changed = ["docker/plain/compose.yaml", "docker/seaweedfs/compose.yaml.j2", "docker/caddy/Dockerfile", "docker/caddy/configs/env.j2"]
        assert ca.excluded_compose_files(tree.root, changed) == []

    def test_deleted_file_is_skipped(self, tree):
        (tree.root / "docker/caddy/compose.yaml").unlink()
        assert ca.excluded_compose_files(tree.root, ["docker/caddy/compose.yaml"]) == []


def runner(root: Path, failing: set[str] = frozenset()):
    calls: list[tuple[list[str], Path, bool]] = []

    def run(args: list[str], cwd: Path) -> int:
        path = args[args.index("-f") + 1]
        calls.append((args, cwd, (root / path).parent.joinpath(".env").exists()))
        return 1 if path in failing else 0

    return run, calls


class TestCheckSyntax:
    def test_runs_config_quiet_from_the_repo_root_and_reports_failures(self, tree):
        run, calls = runner(tree.root, {"docker/seaweedfs/compose.yaml"})
        failed = ca.check_syntax(tree.root, ["docker/caddy/compose.yaml", "docker/seaweedfs/compose.yaml"], run)
        assert failed == ["docker/seaweedfs/compose.yaml"]
        assert [c[0] for c in calls] == [
            ["docker", "compose", "-f", p, "config", "--quiet"] for p in ("docker/caddy/compose.yaml", "docker/seaweedfs/compose.yaml")
        ]
        assert all(c[1] == tree.root for c in calls)

    def test_every_file_is_checked_even_after_a_failure(self, tree):
        run, calls = runner(tree.root, {"docker/caddy/compose.yaml"})
        ca.check_syntax(tree.root, ["docker/caddy/compose.yaml", "docker/seaweedfs/compose.yaml"], run)
        assert len(calls) == 2

    def test_a_missing_env_file_is_stubbed_during_the_check_and_removed_after(self, tree):
        run, calls = runner(tree.root)
        ca.check_syntax(tree.root, ["docker/caddy/compose.yaml"], run)
        assert calls[0][2]
        assert not (tree.root / "docker/caddy/.env").exists()

    def test_the_stub_is_removed_even_when_the_runner_raises(self, tree):
        def boom(args: list[str], cwd: Path) -> int:
            raise RuntimeError("docker exploded")

        with pytest.raises(RuntimeError):
            ca.check_syntax(tree.root, ["docker/caddy/compose.yaml"], boom)
        assert not (tree.root / "docker/caddy/.env").exists()

    def test_an_existing_env_file_is_left_alone(self, tree):
        tree.write("docker/caddy/.env", "REAL=1\n")
        run, _ = runner(tree.root)
        ca.check_syntax(tree.root, ["docker/caddy/compose.yaml"], run)
        assert (tree.root / "docker/caddy/.env").read_text() == "REAL=1\n"


@pytest.fixture
def repo(tree, monkeypatch):
    repo = Repo(tree.root, monkeypatch)
    repo.git("init", "-q")
    repo.base = repo.commit("base")
    return repo


class TestCli:
    def test_changed_writes_apps_dockerfiles_and_excluded_compose_files(self, repo):
        repo.write("docker/lldap/configs/env.j2", "changed\n")
        repo.write("docker/caddy/Dockerfile", "changed\n")
        repo.write("docker/wastebin/Dockerfile", "changed\n")
        repo.write("docker/caddy/compose.yaml", "changed\n")
        head = repo.commit("change")
        assert repo.main("changed", repo.base, head) == 0
        assert repo.out.read_text().splitlines() == [
            'apps=["lldap","wastebin"]',
            'dockerfiles=["caddy","wastebin"]',
            'excluded_compose=["docker/caddy/compose.yaml"]',
        ]

    def test_changed_with_nothing_relevant_writes_empty_arrays(self, repo):
        repo.write("docs/topics/engineering/ci/pipeline.md", "changed\n")
        head = repo.commit("change")
        assert repo.main("changed", repo.base, head) == 0
        assert repo.out.read_text().splitlines() == ["apps=[]", "dockerfiles=[]", "excluded_compose=[]"]

    def test_all_writes_every_app(self, repo):
        assert repo.main("all") == 0
        assert repo.out.read_text().strip() == 'apps=["dashy","lldap","plain","wastebin"]'

    def test_syntax_check_reports_failures_and_exits_nonzero(self, repo):
        repo.write("docker/caddy/compose.yaml", "changed\n")
        head = repo.commit("change")
        assert repo.main("syntax-check", repo.base, head, run=lambda a, c: 1) == 1
        assert repo.main("syntax-check", repo.base, head, run=lambda a, c: 0) == 0

    def test_syntax_check_with_no_excluded_compose_changes_runs_nothing(self, repo):
        repo.write("docker/plain/compose.yaml", "changed\n")
        head = repo.commit("change")

        def fail(args: list[str], cwd: Path) -> int:
            raise AssertionError("docker must not run")

        assert repo.main("syntax-check", repo.base, head, run=fail) == 0

    def test_missing_exclusions_file_fails_the_job(self, repo):
        (repo.root / ca.EXCLUSIONS_FILE).unlink()
        assert repo.main("all") == 1

    def test_bad_revision_fails_the_job(self, repo):
        assert repo.main("changed", "nope", "nope") == 1


class TestRealTree:
    def test_every_exclusion_names_a_real_docker_directory(self, subtests):
        for app in sorted(ca.load_exclusions(ca.REPO_ROOT)):
            with subtests.test(app=app):
                assert (ca.REPO_ROOT / ca.DOCKER_DIR / app).is_dir()

    def test_every_docker_directory_is_a_compose_app_or_excluded(self, subtests):
        excluded = ca.load_exclusions(ca.REPO_ROOT)
        for directory in sorted((ca.REPO_ROOT / ca.DOCKER_DIR).iterdir()):
            if directory.is_dir():
                with subtests.test(app=directory.name):
                    assert ca.has_compose(ca.REPO_ROOT, directory.name) or directory.name in excluded

    def test_the_app_list_is_never_empty_and_never_holds_an_excluded_app(self):
        apps = ca.all_apps(ca.REPO_ROOT)
        assert apps
        assert not set(apps) & ca.load_exclusions(ca.REPO_ROOT)

    def test_the_configs_change_that_motivated_the_rule_queues_lldap(self):
        assert ca.changed_apps(ca.REPO_ROOT, ["docker/lldap/configs/env.j2"]) == ["lldap"]
