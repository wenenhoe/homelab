"""Tests for ci.scope.semantic_diff and its use by molecule_scope.

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

from ci.scope import molecule_scope as ms
from ci.scope import semantic_diff as sd

TASKS = "ansible/roles/alpha/tasks/main.yaml"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def noop(path: str, old: str, new: str) -> bool:
    return sd.is_noop_change(path, old.encode(), new.encode())


class YamlTests(unittest.TestCase):
    BASE = "- name: One\n  ansible.builtin.debug:\n    msg: hi\n"

    def test_comment_added_edited_and_removed_is_a_noop(self):
        commented = "# why\n" + self.BASE.replace("msg: hi", "msg: hi  # trailing")
        self.assertTrue(noop(TASKS, self.BASE, commented))
        self.assertTrue(noop(TASKS, commented, commented.replace("why", "because")))
        self.assertTrue(noop(TASKS, commented, self.BASE))

    def test_formatting_only_is_a_noop(self):
        self.assertTrue(noop(TASKS, self.BASE, "\n\n- name: 'One'\n  ansible.builtin.debug: {msg: hi}\n"))

    def test_value_change_is_real(self):
        self.assertFalse(noop(TASKS, self.BASE, self.BASE.replace("hi", "bye")))

    def test_commenting_out_a_task_is_real(self):
        commented_out = "".join(f"# {line}\n" for line in self.BASE.splitlines())
        self.assertFalse(noop(TASKS, self.BASE, commented_out))

    def test_list_order_change_is_real(self):
        two = self.BASE + "- name: Two\n  ansible.builtin.debug:\n    msg: there\n"
        swapped = "- name: Two\n  ansible.builtin.debug:\n    msg: there\n" + self.BASE
        self.assertFalse(noop(TASKS, two, swapped))

    def test_hash_line_inside_a_block_scalar_is_data_not_a_comment(self):
        script = "- ansible.builtin.copy:\n    content: |\n      {line}\n      keep\n    dest: /x\n"
        self.assertFalse(noop(TASKS, script.format(line="#!/bin/sh"), script.format(line="#!/bin/bash")))
        self.assertFalse(noop(TASKS, script.format(line="#cloud-config"), script.format(line="# cloud-config")))

    def test_multi_document_files_compare_every_document(self):
        self.assertTrue(noop(TASKS, "a: 1\n---\nb: 2\n", "a: 1  # x\n---\nb: 2\n"))
        self.assertFalse(noop(TASKS, "a: 1\n---\nb: 2\n", "a: 1\n---\nb: 3\n"))

    def test_unparseable_or_unsafe_yaml_on_either_side_is_real(self):
        self.assertFalse(noop(TASKS, self.BASE, "- : :\n  [\n"))
        self.assertFalse(noop(TASKS, "- : :\n  [\n", self.BASE))
        self.assertFalse(noop(TASKS, "x: !vault |\n  $ANSIBLE_VAULT;1.1;AES256\n", "# c\nx: !vault |\n  $ANSIBLE_VAULT;1.1;AES256\n"))

    def test_only_yaml_ansible_parses_is_eligible(self):
        commented = "# note\n" + self.BASE
        for path in (
            "ansible/roles/alpha/tasks/sub/other.yml",
            "ansible/roles/alpha/defaults/main.yaml",
            "ansible/roles/alpha/molecule/default/converge.yml",
            "ansible/roles/alpha/molecule/default/host_vars/h.yaml",
            "ansible/roles/molecule_helpers/playbooks/prepare_dind.yml",
            "ansible/roles/molecule_helpers/requirements.yml",
            "ansible/requirements.yml",
            "ansible/inventory/group_vars/all/app_catalog.yaml",
            ".config/molecule/config.yml",
        ):
            with self.subTest(path=path):
                self.assertTrue(noop(path, self.BASE, commented))
        for path in (
            "ansible/roles/molecule_helpers/fixtures/generic_alpine_app/compose.yaml",
            "ansible/roles/alpha/files/user-data.yaml",
            "ansible/roles/alpha/molecule/default/files/docker/app/compose.yaml",
            "docker/app/compose.yaml",
            "ansible/roles/alpha/templates/x.yaml.j2",
            "docs/ci.md",
            "ansible/roles/alpha/tasks/run.sh",
        ):
            with self.subTest(path=path):
                self.assertFalse(noop(path, self.BASE, commented))


class PythonTests(unittest.TestCase):
    BASE = '#!/usr/bin/env python3\n"""Doc."""\n\n\ndef f(x):\n    return x + 1\n'

    def test_comments_and_formatting_are_a_noop(self):
        changed = self.BASE.replace("return x + 1", "# add one\n    return (x + 1)")
        self.assertTrue(noop("ansible/scripts/tool.py", self.BASE, changed))

    def test_code_change_is_real(self):
        self.assertFalse(noop("ansible/scripts/tool.py", self.BASE, self.BASE.replace("x + 1", "x + 2")))

    def test_docstring_change_is_real(self):
        self.assertFalse(noop("ansible/scripts/tool.py", self.BASE, self.BASE.replace("Doc.", "Other.")))

    def test_shebang_change_is_real(self):
        self.assertFalse(noop("ansible/scripts/tool.py", self.BASE, self.BASE.replace("python3", "python")))

    def test_coding_declaration_change_is_real(self):
        with_coding = "# -*- coding: utf-8 -*-\n" + self.BASE
        self.assertFalse(noop("ansible/scripts/tool.py", with_coding, with_coding.replace("utf-8", "latin-1")))

    def test_syntax_error_is_real(self):
        self.assertFalse(noop("ansible/scripts/tool.py", self.BASE, "def f(:\n"))


class TomlTests(unittest.TestCase):
    BASE = '[project]\nname = "x"\ndependencies = ["a>=1"]\n'

    def test_comment_only_is_a_noop_and_value_change_is_real(self):
        self.assertTrue(noop("pyproject.toml", self.BASE, "# note\n" + self.BASE))
        self.assertFalse(noop("pyproject.toml", self.BASE, self.BASE.replace("a>=1", "a>=2")))

    PYPROJECT = (
        '[project]\nname = "x"\ndependencies = ["a>=1"]\n\n[dependency-groups]\ndev = ["pytest"]\n\n[tool.uv]\npackage = false\n\n'
        '[tool.ruff]\nline-length = 160\n\n[tool.ruff.lint]\nselect = ["E"]\n\n[tool.ruff.lint.per-file-ignores]\n"a/**" = ["S101"]\n'
    )

    def test_ruff_tables_are_ignored_in_pyproject(self):
        for change in ("line-length = 100", 'select = ["E", "F"]', '"a/**" = ["S101", "S105"]'):
            edited = self.PYPROJECT.replace("line-length = 160", change) if "line-length" in change else self.PYPROJECT
            if "select" in change:
                edited = self.PYPROJECT.replace('select = ["E"]', change)
            if "a/**" in change:
                edited = self.PYPROJECT.replace('"a/**" = ["S101"]', change)
            with self.subTest(change=change):
                self.assertTrue(noop("pyproject.toml", self.PYPROJECT, edited))

    def test_ruff_table_added_or_removed_is_a_noop(self):
        without = self.PYPROJECT[: self.PYPROJECT.index("[tool.ruff]")]
        self.assertTrue(noop("pyproject.toml", self.PYPROJECT, without))
        self.assertTrue(noop("pyproject.toml", without, self.PYPROJECT))

    def test_every_other_pyproject_table_is_real(self):
        for old, new in (
            ('dependencies = ["a>=1"]', 'dependencies = ["a>=2"]'),
            ('dev = ["pytest"]', 'dev = ["pytest", "molecule"]'),
            ("package = false", "package = true"),
            ('name = "x"', 'name = "y"'),
        ):
            with self.subTest(change=new):
                self.assertFalse(noop("pyproject.toml", self.PYPROJECT, self.PYPROJECT.replace(old, new)))

    def test_a_new_tool_table_is_real(self):
        self.assertFalse(noop("pyproject.toml", self.PYPROJECT, self.PYPROJECT + '\n[tool.pytest.ini_options]\naddopts = "-q"\n'))

    def test_ruff_change_alongside_a_dependency_change_is_real(self):
        edited = self.PYPROJECT.replace("line-length = 160", "line-length = 100").replace("a>=1", "a>=2")
        self.assertFalse(noop("pyproject.toml", self.PYPROJECT, edited))

    def test_the_real_pyproject_has_the_tables_this_relies_on(self):
        import tomllib

        data = tomllib.loads((ms.REPO_ROOT / "pyproject.toml").read_text())
        self.assertIn("ruff", data["tool"])
        self.assertIn("uv", data["tool"])

    def test_uv_lock_is_eligible_and_other_toml_is_not(self):
        self.assertTrue(noop("uv.lock", self.BASE, "# note\n" + self.BASE))
        self.assertFalse(noop("other.toml", self.BASE, "# note\n" + self.BASE))


class NeverNoopTests(unittest.TestCase):
    def test_added_deleted_and_byte_identical_files_are_real(self):
        self.assertFalse(sd.is_noop_change(TASKS, None, b"a: 1\n"))
        self.assertFalse(sd.is_noop_change(TASKS, b"a: 1\n", None))
        # Same bytes means only the mode (or type) changed.
        self.assertFalse(sd.is_noop_change(TASKS, b"a: 1\n", b"a: 1\n"))

    def test_undecodable_bytes_are_real(self):
        self.assertFalse(sd.is_noop_change(TASKS, b"\xff\xfe", b"\xff\xfe# c"))


class ScopeIntegrationTests(unittest.TestCase):
    """molecule_scope.main against a real git history."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        for role in ("alpha", "beta"):
            self.write(f"ansible/roles/{role}/molecule/default/molecule.yml", "provisioner:\n  name: ansible\n")
            self.write(f"ansible/roles/{role}/molecule/default/converge.yml", "- hosts: all\n")
            self.write(f"ansible/roles/{role}/tasks/main.yaml", "- ansible.builtin.debug:\n    msg: hi\n")
        self.write("ansible/roles/molecule_helpers/tasks/orphan.yaml", "- ansible.builtin.debug:\n    msg: hi\n")
        self.write("pyproject.toml", '[project]\nname = "x"\n')
        self.write("ansible/roles/alpha/templates/app.conf.j2", "listen 80;\n")
        self.git("init", "-q")
        self.base = self.commit("base")

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, env={**os.environ, **GIT_ENV}, capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def queued(self) -> str:
        head = self.commit("change")
        out = self.root / "out.txt"
        with patch.object(ms, "REPO_ROOT", self.root), patch.dict(os.environ, {"GITHUB_OUTPUT": str(out)}):
            self.assertEqual(ms.main([self.base, head]), 0)
        return out.read_text().strip()

    def test_comment_only_change_to_a_role_queues_nothing(self):
        self.write("ansible/roles/alpha/tasks/main.yaml", "# why\n- ansible.builtin.debug:\n    msg: hi  # note\n")
        self.assertEqual(self.queued(), "roles=[]")

    def test_real_change_still_queues_the_role(self):
        self.write("ansible/roles/alpha/tasks/main.yaml", "- ansible.builtin.debug:\n    msg: bye\n")
        self.assertEqual(self.queued(), 'roles=["alpha"]')

    def test_comment_and_real_change_together_queue_only_for_the_real_one(self):
        self.write("ansible/roles/alpha/tasks/main.yaml", "# why\n- ansible.builtin.debug:\n    msg: hi\n")
        self.write("ansible/roles/beta/tasks/main.yaml", "- ansible.builtin.debug:\n    msg: bye\n")
        self.assertEqual(self.queued(), 'roles=["beta"]')

    def test_ruff_only_pyproject_change_is_not_repo_wide(self):
        self.write("pyproject.toml", '[project]\nname = "x"\n[tool.ruff]\nline-length = 100\n')
        self.assertEqual(self.queued(), "roles=[]")

    def test_comment_only_pyproject_change_is_not_repo_wide(self):
        self.write("pyproject.toml", '# note\n[project]\nname = "x"\n')
        self.assertEqual(self.queued(), "roles=[]")

    def test_real_pyproject_change_is_still_repo_wide(self):
        self.write("pyproject.toml", '[project]\nname = "y"\n')
        self.assertEqual(self.queued(), 'roles=["alpha","beta"]')

    def test_comment_only_change_to_an_unreferenced_helper_does_not_hit_the_fail_safe(self):
        self.write("ansible/roles/molecule_helpers/tasks/orphan.yaml", "# note\n- ansible.builtin.debug:\n    msg: hi\n")
        self.assertEqual(self.queued(), "roles=[]")

    def test_a_comment_in_a_file_ansible_ships_as_content_is_a_real_change(self):
        self.write("ansible/roles/alpha/templates/app.conf.j2", "# listen\nlisten 80;\n")
        self.assertEqual(self.queued(), 'roles=["alpha"]')

    def test_added_and_deleted_files_are_real_changes(self):
        self.write("ansible/roles/beta/tasks/new.yaml", "# only a comment\n")
        (self.root / "ansible/roles/alpha/tasks/main.yaml").unlink()
        self.assertEqual(self.queued(), 'roles=["alpha","beta"]')

    def test_mode_only_change_is_a_real_change(self):
        (self.root / "ansible/roles/alpha/tasks/main.yaml").chmod(0o755)
        self.assertEqual(self.queued(), 'roles=["alpha"]')


class RealTreeTests(unittest.TestCase):
    def test_real_role_task_files_are_eligible_and_fixtures_are_not(self):
        base = b"- ansible.builtin.debug:\n    msg: hi\n"
        self.assertTrue(sd.is_noop_change("ansible/roles/compose/tasks/init.yaml", base, b"# c\n" + base))
        fixture = "ansible/roles/molecule_helpers/fixtures/generic_alpine_app/compose.yaml"
        self.assertFalse(sd.is_noop_change(fixture, base, b"# c\n" + base))

    def test_every_eligible_yaml_pattern_matches_a_real_file(self):
        root = ms.REPO_ROOT
        files = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts]
        for pattern in sd.ELIGIBLE_YAML:
            with self.subTest(pattern=pattern.pattern):
                self.assertTrue(any(pattern.match(f) for f in files))


if __name__ == "__main__":
    unittest.main()
