"""Unit tests for ci_scope.molecule_scope.

Run via `uv run pytest tools/tests/ -v`. Most cases build a small fake
repo in a temp directory; the last class checks invariants of the real
tree, so a scenario or base-config change that would silently break the
scanner fails here instead of in a PR's detect-changes job.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ci_scope import molecule_scope as ms

CONVERGE_WITH_HELPER = """\
- hosts: all
  tasks:
    - name: Use a helper
      ansible.builtin.include_role:
        name: molecule_helpers
        tasks_from: {tasks_from}
"""

MOLECULE_YML = """\
provisioner:
  name: ansible
  playbooks:
    prepare: ${MOLECULE_PROJECT_DIRECTORY}/../molecule_helpers/playbooks/prepare.yml
"""


class FakeRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def write(self, rel: str, text: str = "---\n") -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def link(self, rel: str, target: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(self.root / target, path.parent), path)

    def scenario(self, role: str, name: str = "default", converge: str = "---\n", molecule_yml: str = "provisioner:\n  name: ansible\n"):
        base = f"ansible/roles/{role}/molecule/{name}"
        self.write(f"{base}/molecule.yml", molecule_yml)
        self.write(f"{base}/converge.yml", converge)

    def helper_task(self, name: str, text: str = "---\n") -> None:
        self.write(f"ansible/roles/molecule_helpers/tasks/{name}", text)

    def roles_for(self, *changed: str) -> list[str]:
        return ms.roles_to_test(self.root, list(changed))[0]


class OwnDirectoryTests(FakeRepo):
    def test_change_inside_a_role_queues_only_that_role(self):
        self.scenario("alpha")
        self.scenario("beta")
        self.assertEqual(self.roles_for("ansible/roles/alpha/tasks/main.yaml"), ["alpha"])

    def test_role_without_molecule_is_ignored(self):
        self.scenario("alpha")
        self.write("ansible/roles/plain/tasks/main.yaml")
        self.assertEqual(self.roles_for("ansible/roles/plain/tasks/main.yaml"), [])

    def test_unrelated_path_queues_nothing(self):
        self.scenario("alpha")
        self.assertEqual(self.roles_for("docs/ci.md"), [])


class GlobalPathTests(FakeRepo):
    def test_every_global_path_queues_every_role(self):
        self.scenario("alpha")
        self.scenario("beta")
        for path in (
            "ansible/requirements.yml",
            "ansible/roles/molecule_helpers/requirements.yml",
            "ansible/roles/molecule_helpers/role-requirements.yml",
            ".config/molecule/config.yml",
            "pyproject.toml",
            "uv.lock",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.roles_for(path), ["alpha", "beta"])


class HelperTaskTests(FakeRepo):
    def test_helper_change_queues_only_consumers(self):
        self.helper_task("one.yaml")
        self.helper_task("two.yaml")
        self.scenario("alpha", converge=CONVERGE_WITH_HELPER.format(tasks_from="one.yaml"))
        self.scenario("beta", converge=CONVERGE_WITH_HELPER.format(tasks_from="two.yaml"))
        self.assertEqual(self.roles_for("ansible/roles/molecule_helpers/tasks/one.yaml"), ["alpha"])

    def test_tasks_from_without_extension_resolves(self):
        self.helper_task("one.yaml")
        self.scenario("alpha", converge=CONVERGE_WITH_HELPER.format(tasks_from="one"))
        self.assertEqual(self.roles_for("ansible/roles/molecule_helpers/tasks/one.yaml"), ["alpha"])

    def test_helper_included_by_another_helper_is_followed(self):
        self.helper_task("outer.yaml", CONVERGE_WITH_HELPER.format(tasks_from="inner.yaml"))
        self.helper_task("inner.yaml")
        self.scenario("alpha", converge=CONVERGE_WITH_HELPER.format(tasks_from="outer.yaml"))
        self.scenario("beta")
        self.assertEqual(self.roles_for("ansible/roles/molecule_helpers/tasks/inner.yaml"), ["alpha"])

    def test_unreferenced_helper_file_queues_every_role(self):
        self.helper_task("orphan.yaml")
        self.scenario("alpha")
        self.scenario("beta")
        self.assertEqual(self.roles_for("ansible/roles/molecule_helpers/tasks/orphan.yaml"), ["alpha", "beta"])

    def test_missing_tasks_from_file_is_an_error(self):
        self.scenario("alpha", converge=CONVERGE_WITH_HELPER.format(tasks_from="gone.yaml"))
        with self.assertRaisesRegex(ms.ScopeError, "matches no file"):
            self.roles_for("docs/ci.md")

    def test_templated_include_role_is_an_error(self):
        templated = "- hosts: all\n  tasks:\n    - ansible.builtin.include_role:\n        name: '{{ which }}'\n"
        self.scenario("alpha", converge=templated)
        with self.assertRaisesRegex(ms.ScopeError, "templated"):
            self.roles_for("docs/ci.md")

    def test_include_of_a_non_helper_role_adds_nothing(self):
        other = "- hosts: all\n  tasks:\n    - ansible.builtin.include_role:\n        name: alpha\n"
        self.scenario("alpha", converge=other)
        self.scenario("beta", converge=other)
        self.assertEqual(self.roles_for("ansible/roles/alpha/tasks/main.yaml"), ["alpha"])


class MoleculeYmlPathTests(FakeRepo):
    def test_prepare_playbook_queues_scenarios_that_reference_it(self):
        self.write("ansible/roles/molecule_helpers/playbooks/prepare.yml")
        self.scenario("alpha", molecule_yml=MOLECULE_YML)
        self.scenario("beta")
        self.assertEqual(self.roles_for("ansible/roles/molecule_helpers/playbooks/prepare.yml"), ["alpha"])

    def test_helper_task_included_by_prepare_playbook_is_followed(self):
        self.helper_task("reset.yaml")
        self.write("ansible/roles/molecule_helpers/playbooks/prepare.yml", CONVERGE_WITH_HELPER.format(tasks_from="reset.yaml"))
        self.scenario("alpha", molecule_yml=MOLECULE_YML)
        self.scenario("beta")
        self.assertEqual(self.roles_for("ansible/roles/molecule_helpers/tasks/reset.yaml"), ["alpha"])

    def test_missing_referenced_path_is_an_error(self):
        self.scenario("alpha", molecule_yml=MOLECULE_YML)
        with self.assertRaisesRegex(ms.ScopeError, "doesn't exist"):
            self.roles_for("docs/ci.md")

    def test_token_used_mid_string_is_an_error(self):
        self.scenario("alpha", molecule_yml="provisioner:\n  env:\n    X: prefix:${MOLECULE_PROJECT_DIRECTORY}/y\n")
        with self.assertRaisesRegex(ms.ScopeError, "mid-string"):
            self.roles_for("docs/ci.md")


class SymlinkTests(FakeRepo):
    def test_change_to_a_symlink_target_queues_the_linking_role(self):
        self.write("docker/app/compose.yaml")
        self.scenario("alpha")
        self.scenario("beta")
        self.link("ansible/roles/alpha/molecule/default/files/docker/app/compose.yaml", "docker/app/compose.yaml")
        self.assertEqual(self.roles_for("docker/app/compose.yaml"), ["alpha"])

    def test_directory_symlink_watches_the_whole_directory(self):
        self.write("docker/app/configs/env.j2")
        self.scenario("alpha")
        self.link("ansible/roles/alpha/molecule/default/files/configs", "docker/app/configs")
        self.assertEqual(self.roles_for("docker/app/configs/env.j2"), ["alpha"])

    def test_dangling_symlink_is_an_error(self):
        self.scenario("alpha")
        self.link("ansible/roles/alpha/molecule/default/files/x", "docker/missing.yaml")
        with self.assertRaisesRegex(ms.ScopeError, "dangling"):
            self.roles_for("docs/ci.md")

    def test_symlink_leaving_the_repo_is_an_error(self):
        self.scenario("alpha")
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "x"
            target.write_text("x")
            path = self.root / "ansible/roles/alpha/molecule/default/files/x"
            path.parent.mkdir(parents=True)
            os.symlink(target, path)
            with self.assertRaisesRegex(ms.ScopeError, "outside the repository"):
                self.roles_for("docs/ci.md")


class CliTests(FakeRepo):
    def git(self, *args: str) -> str:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        return subprocess.run(["git", *args], cwd=self.root, env=env, capture_output=True, text=True, check=True).stdout.strip()

    def test_main_writes_roles_output_from_a_real_diff(self):
        self.scenario("alpha")
        self.scenario("beta")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        base = self.git("rev-parse", "HEAD")
        self.write("ansible/roles/beta/tasks/main.yaml")
        self.git("add", "-A")
        self.git("commit", "-qm", "change")
        head = self.git("rev-parse", "HEAD")
        out = self.root / "out.txt"
        with patch.object(ms, "REPO_ROOT", self.root), patch.dict(os.environ, {"GITHUB_OUTPUT": str(out)}):
            self.assertEqual(ms.main([base, head]), 0)
        self.assertEqual(out.read_text().strip(), 'roles=["beta"]')

    def test_rename_out_of_a_watched_path_counts_as_touching_it(self):
        self.helper_task("one.yaml")
        self.scenario("alpha", converge=CONVERGE_WITH_HELPER.format(tasks_from="one.yaml"))
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        base = self.git("rev-parse", "HEAD")
        self.git("mv", "ansible/roles/molecule_helpers/tasks/one.yaml", "docs-one.yaml")
        self.write("ansible/roles/alpha/molecule/default/converge.yml", CONVERGE_WITH_HELPER.format(tasks_from="one.yaml"))
        self.git("commit", "-qam", "move")
        head = self.git("rev-parse", "HEAD")
        self.assertIn("ansible/roles/molecule_helpers/tasks/one.yaml", ms.changed_files(self.root, base, head))

    def test_scope_error_fails_the_job(self):
        self.scenario("alpha", molecule_yml=MOLECULE_YML)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        head = self.git("rev-parse", "HEAD")
        with patch.object(ms, "REPO_ROOT", self.root):
            self.assertEqual(ms.main([head, head]), 1)


class RealTreeTests(unittest.TestCase):
    """Invariants of the actual repo, not fixtures."""

    def test_every_role_scans_without_error_and_watches_itself(self):
        for role in ms.role_names(ms.REPO_ROOT):
            with self.subTest(role=role):
                self.assertIn(f"ansible/roles/{role}/", ms.watch_set(ms.REPO_ROOT, role))

    def test_global_paths_exist(self):
        for path in ms.GLOBAL_PATHS:
            with self.subTest(path=path):
                self.assertTrue((ms.REPO_ROOT / path).exists())

    def test_base_config_dependency_paths_are_global(self):
        """The base config's Galaxy inputs must all be listed in GLOBAL_PATHS."""
        import yaml

        options = yaml.safe_load((ms.REPO_ROOT / ".config/molecule/config.yml").read_text())["dependency"]["options"]
        role = ms.role_names(ms.REPO_ROOT)[0]
        for value in options.values():
            resolved = Path(os.path.normpath(str(ms.REPO_ROOT / ms.ROLES_DIR / role) + value[len(ms.PROJECT_DIR_TOKEN) :]))
            rel = resolved.relative_to(ms.REPO_ROOT).as_posix()
            with self.subTest(path=rel):
                self.assertTrue(any(rel == g or (g.endswith("/") and rel.startswith(g)) for g in ms.GLOBAL_PATHS))

    def test_a_helper_task_change_no_longer_queues_every_role(self):
        roles = ms.role_names(ms.REPO_ROOT)
        queued = ms.roles_to_test(ms.REPO_ROOT, [f"{ms.HELPERS_DIR}/tasks/start_openbao_test_target.yaml"])[0]
        self.assertTrue(queued)
        self.assertLess(len(queued), len(roles))

    def test_helper_change_json_is_compact_and_sorted(self):
        queued = ms.roles_to_test(ms.REPO_ROOT, ["ansible/roles/apt/tasks/main.yaml"])[0]
        self.assertEqual(json.dumps(queued), '["apt"]')


if __name__ == "__main__":
    unittest.main()
