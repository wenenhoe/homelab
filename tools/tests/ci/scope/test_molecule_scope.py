"""Unit tests for ci.scope.molecule_scope.

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

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.scope import molecule_scope as ms

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


BASE_CONFIG = """\
dependency:
  name: galaxy
  options:
    role-file: ${MOLECULE_PROJECT_DIRECTORY}/../molecule_helpers/role-requirements.yml
    requirements-file: ${MOLECULE_PROJECT_DIRECTORY}/../molecule_helpers/requirements.yml
provisioner:
  env:
    ANSIBLE_ROLES_PATH: ${MOLECULE_PROJECT_DIRECTORY}/../
    ANSIBLE_CONFIG: ${MOLECULE_PROJECT_DIRECTORY}/../../ansible.cfg
    ANSIBLE_CALLBACKS_ENABLED: molecule_coverage
    ANSIBLE_CALLBACK_PLUGINS: ${MOLECULE_PROJECT_DIRECTORY}/../../molecule-coverage/callback_plugins
    MOLECULE_COVERAGE_DIR: ${MOLECULE_PROJECT_DIRECTORY}/../../molecule-coverage/.data
"""


class GlobalPathTests(FakeRepo):
    def with_base_config(self) -> None:
        self.write(".config/molecule/config.yml", BASE_CONFIG)
        self.write("ansible/ansible.cfg", "[defaults]\n")
        self.write("ansible/molecule-coverage/callback_plugins/molecule_coverage.py", "x = 1\n")
        self.write("ansible/roles/molecule_helpers/requirements.yml")
        self.write("ansible/roles/molecule_helpers/role-requirements.yml")
        self.write("ansible/molecule-coverage/thresholds.yaml")

    def test_every_static_global_path_queues_every_role(self):
        self.scenario("alpha")
        self.scenario("beta")
        for path in (*(p for p in ms.GLOBAL_PATHS if not p.endswith("/")), ".config/molecule/config.yml"):
            with self.subTest(path=path):
                self.assertEqual(self.roles_for(path), ["alpha", "beta"])

    def test_every_path_the_base_config_points_scenarios_at_queues_every_role(self):
        self.scenario("alpha")
        self.scenario("beta")
        self.with_base_config()
        for path in (
            "ansible/roles/molecule_helpers/requirements.yml",
            "ansible/roles/molecule_helpers/role-requirements.yml",
            "ansible/ansible.cfg",
            "ansible/molecule-coverage/callback_plugins/molecule_coverage.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.roles_for(path), ["alpha", "beta"])

    def test_base_config_paths_are_resolved_not_listed(self):
        self.scenario("alpha")
        self.with_base_config()
        self.assertEqual(
            ms.base_config_paths(self.root),
            [
                "ansible/ansible.cfg",
                "ansible/molecule-coverage/callback_plugins/",
                "ansible/roles/molecule_helpers/requirements.yml",
                "ansible/roles/molecule_helpers/role-requirements.yml",
            ],
        )

    def test_a_path_the_config_names_moves_with_the_config(self):
        self.scenario("alpha")
        self.scenario("beta")
        self.with_base_config()
        self.write(".config/molecule/config.yml", BASE_CONFIG.replace("../../ansible.cfg", "../../other.cfg"))
        self.write("ansible/other.cfg", "[defaults]\n")
        self.assertEqual(self.roles_for("ansible/other.cfg"), ["alpha", "beta"])
        self.assertEqual(self.roles_for("ansible/ansible.cfg"), [])

    def test_the_roles_directory_and_the_absent_output_directory_are_not_repo_wide(self):
        self.scenario("alpha")
        self.scenario("beta")
        self.with_base_config()
        paths = ms.base_config_paths(self.root)
        self.assertNotIn("ansible/roles/", paths)
        self.assertFalse(any(".data" in p for p in paths))
        self.assertEqual(self.roles_for("ansible/molecule-coverage/.data/run.json"), [])

    def test_the_coverage_thresholds_file_is_read_by_the_gate_not_the_scenario(self):
        self.scenario("alpha")
        self.with_base_config()
        self.assertEqual(self.roles_for("ansible/molecule-coverage/thresholds.yaml"), [])

    def test_no_base_config_means_nothing_extra_is_shared(self):
        self.scenario("alpha")
        self.assertEqual(ms.base_config_paths(self.root), [])

    def test_a_token_in_the_middle_of_a_value_is_an_error(self):
        self.scenario("alpha")
        self.write(".config/molecule/config.yml", "provisioner:\n  env:\n    X: a:${MOLECULE_PROJECT_DIRECTORY}/y\n")
        with self.assertRaisesRegex(ms.ScopeError, "mid-string"):
            ms.base_config_paths(self.root)

    def test_a_comment_only_change_to_ansible_cfg_is_still_a_real_change(self):
        # .cfg is an INI file the interpreter reads for its own values: never a no-op.
        self.scenario("alpha")
        self.with_base_config()
        self.assertEqual(self.roles_for("ansible/ansible.cfg"), ["alpha"])


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

    def test_a_deleted_helper_that_no_scenario_references_needs_nothing_run(self):
        self.helper_task("orphan.yaml")
        self.scenario("alpha")
        self.scenario("beta")
        (self.root / "ansible/roles/molecule_helpers/tasks/orphan.yaml").unlink()
        roles, log = ms.roles_to_test(self.root, ["ansible/roles/molecule_helpers/tasks/orphan.yaml"])
        self.assertEqual(roles, [])
        self.assertIn("deleted, and no scenario references it", log[0])

    def test_deleting_a_helper_that_a_scenario_still_references_fails_the_scan(self):
        self.helper_task("used.yaml")
        self.scenario("alpha", converge=CONVERGE_WITH_HELPER.format(tasks_from="used.yaml"))
        (self.root / "ansible/roles/molecule_helpers/tasks/used.yaml").unlink()
        with self.assertRaisesRegex(ms.ScopeError, "matches no file"):
            self.roles_for("ansible/roles/molecule_helpers/tasks/used.yaml")

    def test_a_deleted_helper_does_not_hide_a_real_change_in_the_same_diff(self):
        self.helper_task("orphan.yaml")
        self.scenario("alpha")
        self.scenario("beta")
        (self.root / "ansible/roles/molecule_helpers/tasks/orphan.yaml").unlink()
        self.assertEqual(self.roles_for("ansible/roles/molecule_helpers/tasks/orphan.yaml", "ansible/roles/beta/tasks/main.yaml"), ["beta"])

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


class RoleIncludeTests(FakeRepo):
    INCLUDE = "- hosts: all\n  tasks:\n    - ansible.builtin.include_role:\n        name: {name}\n"

    def include(self, name: str) -> str:
        return self.INCLUDE.format(name=name)

    def test_scenario_including_a_role_is_queued_when_that_role_changes(self):
        self.scenario("alpha")
        self.scenario("beta", converge=self.include("alpha"))
        self.assertEqual(self.roles_for("ansible/roles/alpha/tasks/main.yaml"), ["alpha", "beta"])
        self.assertEqual(self.roles_for("ansible/roles/beta/tasks/main.yaml"), ["beta"])

    def test_role_including_a_role_in_its_own_tasks_is_queued(self):
        self.scenario("alpha")
        self.scenario("beta")
        self.write("ansible/roles/beta/tasks/main.yaml", self.include("alpha"))
        self.assertEqual(self.roles_for("ansible/roles/alpha/templates/x.j2"), ["alpha", "beta"])

    def test_includes_are_followed_transitively(self):
        self.scenario("alpha")
        self.scenario("beta")
        self.scenario("gamma", converge=self.include("beta"))
        self.write("ansible/roles/beta/tasks/main.yaml", self.include("alpha"))
        self.assertEqual(self.roles_for("ansible/roles/alpha/tasks/main.yaml"), ["alpha", "beta", "gamma"])

    def test_role_without_a_scenario_is_watched_but_never_queued(self):
        self.write("ansible/roles/shared/tasks/main.yaml")
        self.scenario("alpha", converge=self.include("shared"))
        self.assertEqual(self.roles_for("ansible/roles/shared/tasks/main.yaml"), ["alpha"])

    def test_helper_task_that_includes_a_role_watches_that_role(self):
        self.write("ansible/roles/shared/tasks/main.yaml")
        self.helper_task("uses_shared.yaml", self.include("shared"))
        self.scenario("alpha", converge=CONVERGE_WITH_HELPER.format(tasks_from="uses_shared.yaml"))
        self.scenario("beta")
        self.assertEqual(self.roles_for("ansible/roles/shared/tasks/main.yaml"), ["alpha"])

    def test_cycles_terminate(self):
        self.scenario("alpha")
        self.scenario("beta")
        self.write("ansible/roles/alpha/tasks/main.yaml", self.include("beta"))
        self.write("ansible/roles/beta/tasks/main.yaml", self.include("alpha"))
        self.assertEqual(self.roles_for("ansible/roles/alpha/tasks/main.yaml"), ["alpha", "beta"])

    def test_play_roles_list_and_meta_dependencies_are_edges(self):
        self.write("ansible/roles/shared/tasks/main.yaml")
        self.write("ansible/roles/dep/tasks/main.yaml")
        self.scenario("alpha", converge="- hosts: all\n  roles:\n    - role: shared\n")
        self.write("ansible/roles/alpha/meta/main.yml", "dependencies:\n  - dep\n")
        self.scenario("beta")
        self.assertEqual(self.roles_for("ansible/roles/shared/tasks/main.yaml"), ["alpha"])
        self.assertEqual(self.roles_for("ansible/roles/dep/tasks/main.yaml"), ["alpha"])

    def test_collection_role_names_are_ignored(self):
        self.scenario("alpha", converge=self.include("community.general.thing"))
        self.assertEqual(self.roles_for("docs/ci.md"), [])

    def test_including_a_role_that_does_not_exist_is_an_error(self):
        self.scenario("alpha", converge=self.include("ghost"))
        with self.assertRaisesRegex(ms.ScopeError, "not a directory"):
            self.roles_for("docs/ci.md")


class ComputedPathTests(FakeRepo):
    def test_playbook_dir_concatenation_resolves_from_the_scenario_dir(self):
        self.write("ansible/inventory/vars.yaml")
        self.scenario("alpha", converge="- vars:\n    x: \"{{ lookup('file', playbook_dir ~ '/../../../../inventory/vars.yaml') }}\"\n")
        self.scenario("beta")
        self.assertEqual(self.roles_for("ansible/inventory/vars.yaml"), ["alpha"])

    def test_playbook_dir_interpolation_resolves(self):
        self.write("ansible/scripts/tool.py")
        self.scenario("alpha", converge='- src: "{{ playbook_dir }}/../../../../scripts/tool.py"\n')
        self.assertEqual(self.roles_for("ansible/scripts/tool.py"), ["alpha"])

    def test_path_variable_used_in_a_role_template_resolves(self):
        self.write("ansible/roles/molecule_helpers/ansible/files/key.asc")
        self.scenario("alpha", converge="- vars:\n    project_root: \"{{ (playbook_dir ~ '/../../../molecule_helpers') | realpath }}\"\n")
        self.write("ansible/roles/alpha/templates/key.asc.j2", "{{ lookup('file', project_root ~ '/ansible/files/key.asc') }}\n")
        self.scenario("beta")
        self.assertEqual(self.roles_for("ansible/roles/molecule_helpers/ansible/files/key.asc"), ["alpha"])

    BACKUP_LIKE = "- vars:\n    project_root: \"{{ (playbook_dir ~ '/../../../molecule_helpers') | realpath }}\"\n"

    def backup_like_role(self) -> None:
        """The shape backup_agent has: a base directory in the scenario, files read from it in the role."""
        self.write("ansible/roles/molecule_helpers/ansible/files/key.asc")
        self.scenario("alpha", converge=self.BACKUP_LIKE)
        self.write("ansible/roles/alpha/templates/key.asc.j2", "{{ lookup('file', project_root ~ '/ansible/files/key.asc') }}\n")

    def test_a_base_directory_variables_own_definition_is_not_a_read_of_that_directory(self):
        self.backup_like_role()
        watched = ms.watch_set(self.root, "alpha")
        self.assertNotIn("ansible/roles/molecule_helpers/", watched)
        self.assertIn("ansible/roles/molecule_helpers/ansible/files/key.asc", watched)

    def test_an_unreferenced_helper_still_queues_every_role_when_a_role_defines_a_base_directory(self):
        # The over-broad watch this replaces made alpha answer for any helper, hiding the fail-safe.
        self.backup_like_role()
        self.scenario("beta")
        self.write("ansible/roles/molecule_helpers/tasks/orphan.yaml")
        self.assertEqual(self.roles_for("ansible/roles/molecule_helpers/tasks/orphan.yaml"), ["alpha", "beta"])

    def test_only_the_file_a_base_directory_is_joined_to_queues_its_reader(self):
        self.backup_like_role()
        self.scenario("beta")
        self.assertEqual(self.roles_for("ansible/roles/molecule_helpers/ansible/files/key.asc"), ["alpha"])

    def test_a_variable_never_used_as_a_base_is_a_direct_read_of_what_it_names(self):
        self.write("ansible/roles/molecule_helpers/fixtures/data.txt")
        self.scenario("alpha", converge="- src: \"{{ (playbook_dir ~ '/../../../molecule_helpers/fixtures') | realpath }}\"\n")
        self.scenario("beta")
        self.assertEqual(self.roles_for("ansible/roles/molecule_helpers/fixtures/data.txt"), ["alpha"])

    def test_a_variable_used_both_ways_counts_as_a_base(self):
        self.backup_like_role()
        self.write("ansible/roles/alpha/tasks/main.yaml", '- ansible.builtin.debug:\n    msg: "{{ project_root }}/ansible/files/key.asc"\n')
        self.assertNotIn("ansible/roles/molecule_helpers/", ms.watch_set(self.root, "alpha"))

    def test_deleting_a_file_a_scenario_reads_by_a_computed_path_still_queues_the_reader(self):
        self.write("ansible/scripts/tool.py")
        self.scenario("alpha", converge='- src: "{{ playbook_dir }}/../../../../scripts/tool.py"\n')
        self.scenario("beta")
        (self.root / "ansible/scripts/tool.py").unlink()
        self.assertEqual(self.roles_for("ansible/scripts/tool.py"), ["alpha"])

    def test_deleting_the_file_a_base_directory_is_joined_to_still_queues_the_reader(self):
        self.backup_like_role()
        self.scenario("beta")
        (self.root / "ansible/roles/molecule_helpers/ansible/files/key.asc").unlink()
        self.assertEqual(self.roles_for("ansible/roles/molecule_helpers/ansible/files/key.asc"), ["alpha"])

    def test_path_variable_defined_and_used_in_a_scenario_resolves(self):
        self.write("docker/app/configs/x.j2")
        converge = (
            "- vars:\n"
            "    repo_root: \"{{ (playbook_dir ~ '/../../../../../') | realpath }}\"\n"
            "  x: |\n"
            "    {{ lookup('template', repo_root ~ '/docker/app/configs/x.j2') }}\n"
        )
        self.scenario("alpha", converge=converge)
        self.assertEqual(self.roles_for("docker/app/configs/x.j2"), ["alpha"])

    def test_path_variable_undefined_in_the_scenario_is_ignored(self):
        self.write("ansible/files/key.asc")
        self.scenario("alpha")
        self.write("ansible/roles/alpha/templates/key.asc.j2", "{{ lookup('file', project_root ~ '/ansible/files/key.asc') }}\n")
        self.assertEqual(self.roles_for("ansible/files/key.asc"), [])

    def test_nonexistent_computed_path_is_ignored(self):
        self.scenario("alpha", converge="- x: \"{{ playbook_dir ~ '/../../../../nope.yaml' }}\"\n")
        self.assertEqual(self.roles_for("docs/ci.md"), [])

    def test_literal_continued_with_a_tilde_is_a_partial_path_and_ignored(self):
        self.write("ansible/files/telegram-pins/.lock-")
        self.scenario("alpha", converge="- x: \"{{ playbook_dir ~ '/../../../../files/telegram-pins/.lock-' ~ key }}\"\n")
        self.assertEqual(self.roles_for("ansible/files/telegram-pins/.lock-"), [])

    def test_path_that_is_the_repo_root_or_an_ancestor_of_the_role_is_ignored(self):
        self.write("README.md")
        converge = "- vars:\n    repo_root: \"{{ (playbook_dir ~ '/../../../../../') | realpath }}\"\n  x: \"{{ repo_root ~ '/' }}\"\n"
        self.scenario("alpha", converge=converge)
        self.assertEqual(self.roles_for("README.md"), [])

    def test_computed_path_inside_the_role_adds_nothing_extra(self):
        self.scenario("alpha", converge='- src: "{{ playbook_dir }}/files/docker"\n')
        watched = ms.watch_set(self.root, "alpha")
        self.assertEqual(list(watched), ["ansible/roles/alpha/"])


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


class FilterPluginTests(FakeRepo):
    PLUGIN = "ansible/filter_plugins/my_plugin.py"

    def plugin(self, *names: str, file: str = "my_plugin") -> str:
        entries = ", ".join(f'"{name}": len' for name in names)
        path = f"ansible/filter_plugins/{file}.py"
        self.write(path, f"class FilterModule:\n    def filters(self):\n        return {{{entries}}}\n")
        return path

    def uses(self, role: str, text: str, where: str = "tasks/main.yaml") -> None:
        self.write(f"ansible/roles/{role}/{where}", text)

    def test_a_filter_change_queues_only_the_roles_that_call_it(self):
        plugin = self.plugin("my_filter")
        for role in ("alpha", "beta", "gamma"):
            self.scenario(role)
        self.uses("alpha", '- ansible.builtin.debug:\n    msg: "{{ x | my_filter }}"\n')
        self.uses("beta", "- ansible.builtin.debug:\n    msg: nothing\n")
        self.assertEqual(self.roles_for(plugin), ["alpha"])

    def test_a_template_defaults_or_scenario_file_counts_as_a_call(self):
        plugin = self.plugin("my_filter")
        for role in ("alpha", "beta", "gamma", "delta"):
            self.scenario(role)
        self.uses("alpha", "{{ value | my_filter }}\n", "templates/unit.j2")
        self.uses("beta", 'beta_value: "{{ 3 | my_filter }}"\n', "defaults/main.yaml")
        self.write("ansible/roles/gamma/molecule/default/verify.yml", '- ansible.builtin.assert:\n    that: "1 | my_filter"\n')
        self.assertEqual(self.roles_for(plugin), ["alpha", "beta", "gamma"])

    def test_a_call_in_an_included_role_queues_the_role_that_runs_it(self):
        plugin = self.plugin("my_filter")
        for role in ("alpha", "beta", "gamma"):
            self.scenario(role)
        self.uses("alpha", "- ansible.builtin.include_role:\n    name: beta\n")
        self.uses("beta", '- ansible.builtin.debug:\n    msg: "{{ 1 | my_filter }}"\n')
        self.assertEqual(self.roles_for(plugin), ["alpha", "beta"])

    def test_a_call_in_a_helper_task_a_scenario_pulls_in_counts(self):
        plugin = self.plugin("my_filter")
        self.scenario("alpha", converge=CONVERGE_WITH_HELPER.format(tasks_from="shared.yaml"))
        self.scenario("beta")
        self.helper_task("shared.yaml", '- ansible.builtin.debug:\n    msg: "{{ 1 | my_filter }}"\n')
        self.assertEqual(self.roles_for(plugin), ["alpha"])

    def test_any_filter_a_module_defines_counts(self):
        plugin = self.plugin("first_filter", "second_filter")
        self.scenario("alpha")
        self.scenario("beta")
        self.uses("beta", 'msg: "{{ x | second_filter }}"\n')
        self.assertEqual(self.roles_for(plugin), ["beta"])

    def test_the_bare_name_in_map_or_select_counts(self):
        plugin = self.plugin("my_filter")
        self.scenario("alpha")
        self.uses("alpha", "msg: \"{{ items | map('my_filter') | list }}\"\n")
        self.assertEqual(self.roles_for(plugin), ["alpha"])

    def test_the_name_has_to_stand_alone(self):
        plugin = self.plugin("my_filter")
        self.scenario("alpha")
        self.uses("alpha", 'a: "{{ compose_my_filter }}"\nb: "{{ item.my_filter }}"\nc: "{{ my_filter_extra }}"\n')
        self.assertEqual(self.roles_for(plugin), [])

    def test_a_filter_no_role_calls_queues_nothing_and_says_so(self):
        plugin = self.plugin("my_filter")
        self.scenario("alpha")
        roles, log = ms.roles_to_test(self.root, [plugin])
        self.assertEqual(roles, [])
        self.assertIn(f"{plugin}: no role's Molecule run uses its filters -> nothing to run", log)

    def test_the_watch_set_says_which_filter_and_which_file(self):
        plugin = self.plugin("my_filter")
        self.scenario("alpha")
        self.uses("alpha", 'msg: "{{ 1 | my_filter }}"\n')
        self.assertEqual(ms.watch_set(self.root, "alpha")[plugin], ["uses filter my_filter (ansible/roles/alpha/tasks/main.yaml)"])

    def test_a_comment_only_change_to_a_plugin_queues_nothing(self):
        plugin = self.plugin("my_filter")
        self.scenario("alpha")
        self.uses("alpha", 'msg: "{{ 1 | my_filter }}"\n')
        roles, log = ms.roles_to_test(self.root, [plugin], is_noop=lambda path: True)
        self.assertEqual(roles, [])
        self.assertIn(f"{plugin}: comments/formatting only -> ignored", log)

    def test_a_file_whose_filters_cannot_be_read_queues_every_role(self):
        self.scenario("alpha")
        self.scenario("beta")
        unreadable = {
            "built by a call": "class FilterModule:\n    def filters(self):\n        return dict(a=len)\n",
            "built by a helper": "class FilterModule:\n    def filters(self):\n        return build()\n",
            "spread into the dict": "class FilterModule:\n    def filters(self):\n        return {**base(), 'a': len}\n",
            "an empty dict": "class FilterModule:\n    def filters(self):\n        return {}\n",
            "no FilterModule at all": "def shared_helper():\n    return 1\n",
            "a syntax error": "class FilterModule(:\n",
        }
        for label, text in unreadable.items():
            with self.subTest(label):
                path = f"ansible/filter_plugins/{label.replace(' ', '_')}.py"
                self.write(path, text)
                roles, log = ms.roles_to_test(self.root, [path])
                self.assertEqual(roles, ["alpha", "beta"])
                self.assertIn(f"{path}: under ansible/filter_plugins/ but not a plugin whose filter names can be read -> every role", log)

    def test_a_deleted_nested_or_non_python_file_queues_every_role(self):
        self.plugin("my_filter")
        self.write("ansible/filter_plugins/sub/nested.py", "x = 1\n")
        self.write("ansible/filter_plugins/README.md", "notes\n")
        self.scenario("alpha")
        self.scenario("beta")
        for label, path in (
            ("deleted", "ansible/filter_plugins/gone.py"),
            ("nested", "ansible/filter_plugins/sub/nested.py"),
            ("non-python", "ansible/filter_plugins/README.md"),
        ):
            with self.subTest(label):
                self.assertEqual(self.roles_for(path), ["alpha", "beta"])

    def test_a_readable_plugin_is_not_a_repo_wide_path(self):
        self.assertNotIn("ansible/filter_plugins/", ms.GLOBAL_PATHS)


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

    def test_the_real_base_config_resolves_to_what_every_scenario_is_pointed_at(self):
        self.assertEqual(
            ms.base_config_paths(ms.REPO_ROOT),
            [
                "ansible/ansible.cfg",
                "ansible/molecule-coverage/callback_plugins/",
                "ansible/roles/molecule_helpers/requirements.yml",
                "ansible/roles/molecule_helpers/role-requirements.yml",
            ],
        )

    def test_every_project_directory_path_in_the_base_config_is_accounted_for(self):
        """Each is repo-wide, or one of the two deliberate exclusions; none is silently dropped."""
        import yaml

        role_dir = ms.REPO_ROOT / ms.ROLES_DIR / ms.role_names(ms.REPO_ROOT)[0]
        repo_wide = ms.base_config_paths(ms.REPO_ROOT)
        deliberately_not = {"ansible/roles", "ansible/molecule-coverage/.data"}
        for node in ms._walk(yaml.safe_load((ms.REPO_ROOT / ms.BASE_CONFIG).read_text())):
            if isinstance(node, str) and node.startswith(ms.PROJECT_DIR_TOKEN):
                rel = Path(os.path.normpath(str(role_dir) + node[len(ms.PROJECT_DIR_TOKEN) :])).relative_to(ms.REPO_ROOT).as_posix()
                with self.subTest(path=rel):
                    self.assertTrue(rel in deliberately_not or any(g.rstrip("/") == rel for g in repo_wide), rel)

    def test_a_change_to_ansible_cfg_or_the_coverage_callback_queues_every_role(self):
        roles = ms.role_names(ms.REPO_ROOT)
        for path in ("ansible/ansible.cfg", "ansible/molecule-coverage/callback_plugins/molecule_coverage.py"):
            with self.subTest(path=path):
                self.assertEqual(ms.roles_to_test(ms.REPO_ROOT, [path])[0], roles)

    def test_the_thresholds_file_and_the_gate_package_do_not_queue_scenarios(self):
        for path in ("ansible/molecule-coverage/thresholds.yaml", "ansible/molecule-coverage/molecule_cov/cli.py"):
            with self.subTest(path=path):
                self.assertEqual(ms.roles_to_test(ms.REPO_ROOT, [path])[0], [])

    def test_no_role_watches_the_whole_helpers_directory(self):
        # backup_agent used to, through the definition of its project_root variable.
        for role in ms.role_names(ms.REPO_ROOT):
            with self.subTest(role=role):
                self.assertNotIn(f"{ms.HELPERS_DIR}/", ms.watch_set(ms.REPO_ROOT, role))

    def test_backup_agent_still_watches_the_one_helper_file_it_reads(self):
        watched = ms.watch_set(ms.REPO_ROOT, "backup_agent")
        self.assertIn(f"{ms.HELPERS_DIR}/ansible/files/backup-gpg-public-key.asc", watched)

    def test_deleting_the_removed_bootstrap_helper_queues_nothing(self):
        # The change that removed it, as detect-changes saw it.
        queued, log = ms.roles_to_test(ms.REPO_ROOT, [f"{ms.HELPERS_DIR}/tasks/bootstrap_docker.yaml"])
        self.assertEqual(queued, [])
        self.assertIn("deleted", log[0])

    def test_a_helper_task_change_no_longer_queues_every_role(self):
        roles = ms.role_names(ms.REPO_ROOT)
        queued = ms.roles_to_test(ms.REPO_ROOT, [f"{ms.HELPERS_DIR}/tasks/start_openbao_test_target.yaml"])[0]
        self.assertTrue(queued)
        self.assertLess(len(queued), len(roles))

    def test_compose_change_queues_the_roles_that_run_it(self):
        queued = ms.roles_to_test(ms.REPO_ROOT, ["ansible/roles/compose/tasks/init.yaml"])[0]
        for role in ("compose", "compose_app", "caddy", "tinyauth", "bind9"):
            self.assertIn(role, queued)

    def test_shared_notification_roles_queue_their_callers(self):
        for shared in ("telegram_notify", "uptime_kuma_push"):
            queued = ms.roles_to_test(ms.REPO_ROOT, [f"ansible/roles/{shared}/tasks/install.yaml"])[0]
            for caller in ("step_ca_cert", "cloud_sync", "caddy_cert_expiry"):
                with self.subTest(shared=shared, caller=caller):
                    self.assertIn(caller, queued)

    def test_app_registry_change_queues_the_scenarios_that_read_it(self):
        queued = ms.roles_to_test(ms.REPO_ROOT, ["ansible/inventory/group_vars/all/app_registry.yaml"])[0]
        for role in ("bind9", "caddy", "tinyauth", "step_ca_cert"):
            self.assertIn(role, queued)

    def test_restore_script_change_queues_restore_discovery(self):
        self.assertEqual(ms.roles_to_test(ms.REPO_ROOT, ["ansible/scripts/restore_all.py"])[0], ["restore_discovery"])

    def test_the_role_whose_scenario_reads_its_own_helper_key_is_watched(self):
        watched = ms.watch_set(ms.REPO_ROOT, "backup_agent")
        self.assertIn("ansible/roles/molecule_helpers/ansible/files/backup-gpg-public-key.asc", watched)

    def test_editing_a_filter_queues_the_roles_that_call_it_not_every_role(self):
        queued = ms.roles_to_test(ms.REPO_ROOT, ["ansible/filter_plugins/cron_period_hours.py"])[0]
        self.assertIn("backup_agent", queued)
        self.assertLess(len(queued), len(ms.role_names(ms.REPO_ROOT)))

    def test_every_real_filter_plugin_has_names_the_scanner_can_read(self):
        # An unreadable one would quietly queue every role whenever it changed.
        plugins = ms.filter_plugins(ms.REPO_ROOT)
        self.assertTrue(plugins)
        for plugin, names in plugins.items():
            with self.subTest(plugin=plugin):
                self.assertTrue(names, f"{plugin}: FilterModule.filters() must return a dict literal of string keys")

    def test_helper_change_json_is_compact_and_sorted(self):
        queued = ms.roles_to_test(ms.REPO_ROOT, ["ansible/roles/apt/tasks/main.yaml"])[0]
        self.assertEqual(json.dumps(queued), '["apt"]')


if __name__ == "__main__":
    unittest.main()
