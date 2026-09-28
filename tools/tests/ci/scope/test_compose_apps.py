"""Tests for ci.scope.compose_apps.

Function-level cases build a scratch docker/ tree; the CLI cases run
`main` against a real git history; the last class checks invariants of the
actual repo. The syntax check goes through a stub runner, so nothing needs
docker.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.scope import compose_apps as ca

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class Scratch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.write(ca.EXCLUSIONS_FILE, "# excluded\n\ncaddy\n  seaweedfs  \n# tinyauth is only mentioned in a comment\n")
        for app in ("lldap", "wastebin", "caddy", "dashy", "plain", "seaweedfs"):
            self.write(f"docker/{app}/compose.yaml{'.j2' if app == 'lldap' else ''}")
        self.write("docker/lldap/configs/env.j2")
        self.write("docker/lldap/scripts/run.sh")
        self.write("docker/wastebin/Dockerfile")
        self.write("docker/caddy/Dockerfile")
        self.write("docker/caddy/configs/env.j2")
        self.write("docker/dashy/configs/conf.yaml.j2")
        self.write("docker/openbao/policies/controller.hcl")
        self.write("docker/molecule-dind/Dockerfile")
        self.write("docs/ci.md")

    def write(self, rel: str, text: str = "x\n") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


class ExclusionTests(Scratch):
    def test_comments_blank_lines_and_whitespace_are_ignored(self):
        self.assertEqual(ca.load_exclusions(self.root), {"caddy", "seaweedfs"})

    def test_missing_file_is_an_error(self):
        (self.root / ca.EXCLUSIONS_FILE).unlink()
        with self.assertRaisesRegex(ca.ComposeAppsError, "can't read"):
            ca.load_exclusions(self.root)


class AllAppsTests(Scratch):
    def test_lists_compose_apps_sorted_minus_excluded(self):
        self.assertEqual(ca.all_apps(self.root), ["dashy", "lldap", "plain", "wastebin"])

    def test_directory_without_a_compose_file_is_not_an_app(self):
        self.assertNotIn("openbao", ca.all_apps(self.root))
        self.assertNotIn("molecule-dind", ca.all_apps(self.root))

    def test_templated_compose_file_counts(self):
        self.assertIn("lldap", ca.all_apps(self.root))


class ChangedAppsTests(Scratch):
    def apps(self, *changed: str) -> list[str]:
        return ca.changed_apps(self.root, list(changed))

    def test_configs_change(self):
        self.assertEqual(self.apps("docker/lldap/configs/env.j2"), ["lldap"])

    def test_nested_configs_change(self):
        self.assertEqual(self.apps("docker/lldap/configs/sub/dir/x.j2"), ["lldap"])

    def test_scripts_change(self):
        self.assertEqual(self.apps("docker/lldap/scripts/run.sh"), ["lldap"])

    def test_templated_compose_change(self):
        self.assertEqual(self.apps("docker/lldap/compose.yaml.j2"), ["lldap"])

    def test_plain_compose_change(self):
        self.assertEqual(self.apps("docker/plain/compose.yaml"), ["plain"])

    def test_dockerfile_change_queues_the_app(self):
        self.assertEqual(self.apps("docker/wastebin/Dockerfile"), ["wastebin"])

    def test_excluded_app_is_never_queued(self):
        self.assertEqual(self.apps("docker/caddy/configs/env.j2", "docker/caddy/Dockerfile", "docker/caddy/compose.yaml"), [])

    def test_directory_without_a_compose_file_is_never_queued(self):
        self.assertEqual(self.apps("docker/molecule-dind/Dockerfile", "docker/openbao/configs/x.j2"), [])

    def test_files_outside_configs_scripts_compose_and_dockerfile_are_ignored(self):
        self.assertEqual(self.apps("docker/openbao/policies/controller.hcl", "docker/lldap/README.md", "docs/ci.md"), [])

    def test_only_a_bare_configs_directory_name_is_not_enough(self):
        self.assertEqual(self.apps("docker/lldap/configs"), [])

    def test_a_similarly_named_file_is_not_a_compose_file(self):
        self.assertEqual(self.apps("docker/plain/compose.yaml.bak", "docker/plain/docker-compose.yaml", "docker/plain/sub/Dockerfile"), [])

    def test_deleting_only_a_config_still_queues_the_app(self):
        (self.root / "docker/lldap/configs/env.j2").unlink()
        self.assertEqual(self.apps("docker/lldap/configs/env.j2"), ["lldap"])

    def test_deleting_the_whole_app_queues_nothing(self):
        import shutil

        shutil.rmtree(self.root / "docker/dashy")
        self.assertEqual(self.apps("docker/dashy/compose.yaml", "docker/dashy/configs/conf.yaml.j2"), [])

    def test_two_apps_are_sorted_and_deduplicated(self):
        self.assertEqual(
            self.apps("docker/lldap/configs/env.j2", "docker/dashy/configs/conf.yaml.j2", "docker/lldap/scripts/run.sh"),
            ["dashy", "lldap"],
        )


class ChangedDockerfilesTests(Scratch):
    def test_excluded_and_composeless_apps_are_included(self):
        self.assertEqual(
            ca.changed_dockerfiles(self.root, ["docker/caddy/Dockerfile", "docker/molecule-dind/Dockerfile", "docker/wastebin/Dockerfile"]),
            ["caddy", "molecule-dind", "wastebin"],
        )

    def test_only_the_dockerfile_itself_counts(self):
        self.assertEqual(ca.changed_dockerfiles(self.root, ["docker/caddy/compose.yaml", "docker/lldap/configs/env.j2", "docker/caddy/sub/Dockerfile"]), [])

    def test_deleted_dockerfile_is_not_queued(self):
        (self.root / "docker/wastebin/Dockerfile").unlink()
        self.assertEqual(ca.changed_dockerfiles(self.root, ["docker/wastebin/Dockerfile"]), [])


class ExcludedComposeFilesTests(Scratch):
    def test_changed_compose_yaml_of_an_excluded_app_is_listed(self):
        self.write("docker/caddy/compose.override.yaml")
        self.assertEqual(
            ca.excluded_compose_files(self.root, ["docker/caddy/compose.yaml", "docker/caddy/compose.override.yaml", "docker/seaweedfs/compose.yaml"]),
            ["docker/caddy/compose.override.yaml", "docker/caddy/compose.yaml", "docker/seaweedfs/compose.yaml"],
        )

    def test_non_excluded_apps_and_templates_and_other_files_are_not(self):
        self.write("docker/seaweedfs/compose.yaml.j2")
        changed = ["docker/plain/compose.yaml", "docker/seaweedfs/compose.yaml.j2", "docker/caddy/Dockerfile", "docker/caddy/configs/env.j2"]
        self.assertEqual(ca.excluded_compose_files(self.root, changed), [])

    def test_deleted_file_is_skipped(self):
        (self.root / "docker/caddy/compose.yaml").unlink()
        self.assertEqual(ca.excluded_compose_files(self.root, ["docker/caddy/compose.yaml"]), [])


class CheckSyntaxTests(Scratch):
    def runner(self, failing: set[str] = frozenset()):
        calls: list[tuple[list[str], Path, bool]] = []

        def run(args: list[str], cwd: Path) -> int:
            path = args[args.index("-f") + 1]
            calls.append((args, cwd, (self.root / path).parent.joinpath(".env").exists()))
            return 1 if path in failing else 0

        return run, calls

    def test_runs_config_quiet_from_the_repo_root_and_reports_failures(self):
        run, calls = self.runner({"docker/seaweedfs/compose.yaml"})
        failed = ca.check_syntax(self.root, ["docker/caddy/compose.yaml", "docker/seaweedfs/compose.yaml"], run)
        self.assertEqual(failed, ["docker/seaweedfs/compose.yaml"])
        self.assertEqual(
            [c[0] for c in calls], [["docker", "compose", "-f", p, "config", "--quiet"] for p in ("docker/caddy/compose.yaml", "docker/seaweedfs/compose.yaml")]
        )
        self.assertTrue(all(c[1] == self.root for c in calls))

    def test_every_file_is_checked_even_after_a_failure(self):
        run, calls = self.runner({"docker/caddy/compose.yaml"})
        ca.check_syntax(self.root, ["docker/caddy/compose.yaml", "docker/seaweedfs/compose.yaml"], run)
        self.assertEqual(len(calls), 2)

    def test_a_missing_env_file_is_stubbed_during_the_check_and_removed_after(self):
        run, calls = self.runner()
        ca.check_syntax(self.root, ["docker/caddy/compose.yaml"], run)
        self.assertTrue(calls[0][2])
        self.assertFalse((self.root / "docker/caddy/.env").exists())

    def test_the_stub_is_removed_even_when_the_runner_raises(self):
        def boom(args: list[str], cwd: Path) -> int:
            raise RuntimeError("docker exploded")

        with self.assertRaises(RuntimeError):
            ca.check_syntax(self.root, ["docker/caddy/compose.yaml"], boom)
        self.assertFalse((self.root / "docker/caddy/.env").exists())

    def test_an_existing_env_file_is_left_alone(self):
        self.write("docker/caddy/.env", "REAL=1\n")
        run, _ = self.runner()
        ca.check_syntax(self.root, ["docker/caddy/compose.yaml"], run)
        self.assertEqual((self.root / "docker/caddy/.env").read_text(), "REAL=1\n")


class CliTests(Scratch):
    def setUp(self):
        super().setUp()
        self.git("init", "-q")
        self.base = self.commit("base")
        self.out = self.root / "out.txt"

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, env={**os.environ, **GIT_ENV}, capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def main(self, *argv: str, run=None) -> int:
        with patch.object(ca, "REPO_ROOT", self.root), patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.out)}):
            return ca.main(list(argv), run) if run else ca.main(list(argv))

    def test_changed_writes_apps_and_dockerfiles(self):
        self.write("docker/lldap/configs/env.j2", "changed\n")
        self.write("docker/caddy/Dockerfile", "changed\n")
        self.write("docker/wastebin/Dockerfile", "changed\n")
        head = self.commit("change")
        self.assertEqual(self.main("changed", self.base, head), 0)
        self.assertEqual(
            self.out.read_text().splitlines(),
            ['apps=["lldap","wastebin"]', 'dockerfiles=["caddy","wastebin"]'],
        )

    def test_changed_with_nothing_relevant_writes_empty_arrays(self):
        self.write("docs/ci.md", "changed\n")
        head = self.commit("change")
        self.assertEqual(self.main("changed", self.base, head), 0)
        self.assertEqual(self.out.read_text().splitlines(), ["apps=[]", "dockerfiles=[]"])

    def test_all_writes_every_app(self):
        self.assertEqual(self.main("all"), 0)
        self.assertEqual(self.out.read_text().strip(), 'apps=["dashy","lldap","plain","wastebin"]')

    def test_syntax_check_reports_failures_and_exits_nonzero(self):
        self.write("docker/caddy/compose.yaml", "changed\n")
        head = self.commit("change")
        self.assertEqual(self.main("syntax-check", self.base, head, run=lambda a, c: 1), 1)
        self.assertEqual(self.main("syntax-check", self.base, head, run=lambda a, c: 0), 0)

    def test_syntax_check_with_no_excluded_compose_changes_runs_nothing(self):
        self.write("docker/plain/compose.yaml", "changed\n")
        head = self.commit("change")

        def fail(args: list[str], cwd: Path) -> int:
            raise AssertionError("docker must not run")

        self.assertEqual(self.main("syntax-check", self.base, head, run=fail), 0)

    def test_missing_exclusions_file_fails_the_job(self):
        (self.root / ca.EXCLUSIONS_FILE).unlink()
        self.assertEqual(self.main("all"), 1)

    def test_bad_revision_fails_the_job(self):
        self.assertEqual(self.main("changed", "nope", "nope"), 1)


class RealTreeTests(unittest.TestCase):
    def test_every_exclusion_names_a_real_docker_directory(self):
        for app in sorted(ca.load_exclusions(ca.REPO_ROOT)):
            with self.subTest(app=app):
                self.assertTrue((ca.REPO_ROOT / ca.DOCKER_DIR / app).is_dir())

    def test_every_docker_directory_is_a_compose_app_or_excluded(self):
        excluded = ca.load_exclusions(ca.REPO_ROOT)
        for directory in sorted((ca.REPO_ROOT / ca.DOCKER_DIR).iterdir()):
            if directory.is_dir():
                with self.subTest(app=directory.name):
                    self.assertTrue(ca.has_compose(ca.REPO_ROOT, directory.name) or directory.name in excluded)

    def test_the_app_list_is_never_empty_and_never_holds_an_excluded_app(self):
        apps = ca.all_apps(ca.REPO_ROOT)
        self.assertTrue(apps)
        self.assertFalse(set(apps) & ca.load_exclusions(ca.REPO_ROOT))

    def test_the_configs_change_that_motivated_the_rule_queues_lldap(self):
        self.assertEqual(ca.changed_apps(ca.REPO_ROOT, ["docker/lldap/configs/env.j2"]), ["lldap"])


if __name__ == "__main__":
    unittest.main()
