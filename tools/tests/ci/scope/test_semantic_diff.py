"""Tests for ci.scope.semantic_diff and its use by molecule_scope.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

import pytest
from ci.scope import molecule_scope as ms
from ci.scope import semantic_diff as sd

TASKS = "ansible/roles/alpha/tasks/main.yaml"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def noop(path: str, old: str, new: str) -> bool:
    return sd.is_noop_change(path, old.encode(), new.encode())


class TestYaml:
    BASE = "- name: One\n  ansible.builtin.debug:\n    msg: hi\n"

    def test_comment_added_edited_and_removed_is_a_noop(self):
        commented = "# why\n" + self.BASE.replace("msg: hi", "msg: hi  # trailing")
        assert noop(TASKS, self.BASE, commented)
        assert noop(TASKS, commented, commented.replace("why", "because"))
        assert noop(TASKS, commented, self.BASE)

    def test_formatting_only_is_a_noop(self):
        assert noop(TASKS, self.BASE, "\n\n- name: 'One'\n  ansible.builtin.debug: {msg: hi}\n")

    def test_value_change_is_real(self):
        assert not noop(TASKS, self.BASE, self.BASE.replace("hi", "bye"))

    def test_commenting_out_a_task_is_real(self):
        commented_out = "".join(f"# {line}\n" for line in self.BASE.splitlines())
        assert not noop(TASKS, self.BASE, commented_out)

    def test_list_order_change_is_real(self):
        two = self.BASE + "- name: Two\n  ansible.builtin.debug:\n    msg: there\n"
        swapped = "- name: Two\n  ansible.builtin.debug:\n    msg: there\n" + self.BASE
        assert not noop(TASKS, two, swapped)

    def test_hash_line_inside_a_block_scalar_is_data_not_a_comment(self):
        script = "- ansible.builtin.copy:\n    content: |\n      {line}\n      keep\n    dest: /x\n"
        assert not noop(TASKS, script.format(line="#!/bin/sh"), script.format(line="#!/bin/bash"))
        assert not noop(TASKS, script.format(line="#cloud-config"), script.format(line="# cloud-config"))

    def test_multi_document_files_compare_every_document(self):
        assert noop(TASKS, "a: 1\n---\nb: 2\n", "a: 1  # x\n---\nb: 2\n")
        assert not noop(TASKS, "a: 1\n---\nb: 2\n", "a: 1\n---\nb: 3\n")

    def test_unparseable_or_unsafe_yaml_on_either_side_is_real(self):
        assert not noop(TASKS, self.BASE, "- : :\n  [\n")
        assert not noop(TASKS, "- : :\n  [\n", self.BASE)
        assert not noop(TASKS, "x: !vault |\n  $ANSIBLE_VAULT;1.1;AES256\n", "# c\nx: !vault |\n  $ANSIBLE_VAULT;1.1;AES256\n")

    @pytest.mark.parametrize(
        "path",
        [
            "ansible/roles/alpha/tasks/sub/other.yml",
            "ansible/roles/alpha/defaults/main.yaml",
            "ansible/roles/alpha/molecule/default/converge.yml",
            "ansible/roles/alpha/molecule/default/host_vars/h.yaml",
            "ansible/roles/molecule_helpers/playbooks/prepare_dind.yml",
            "ansible/roles/molecule_helpers/requirements.yml",
            "ansible/requirements.yml",
            "ansible/inventory/group_vars/all/app_catalog.yaml",
            ".config/molecule/config.yml",
        ],
    )
    def test_only_yaml_ansible_parses_is_eligible(self, path):
        commented = "# note\n" + self.BASE
        assert noop(path, self.BASE, commented)

    @pytest.mark.parametrize(
        "path",
        [
            "ansible/roles/molecule_helpers/fixtures/generic_alpine_app/compose.yaml",
            "ansible/roles/alpha/files/user-data.yaml",
            "ansible/roles/alpha/molecule/default/files/docker/app/compose.yaml",
            "docker/app/compose.yaml",
            "ansible/roles/alpha/templates/x.yaml.j2",
            "docs/topics/engineering/ci/pipeline.md",
            "ansible/roles/alpha/tasks/run.sh",
        ],
    )
    def test_every_other_path_is_not_eligible(self, path):
        commented = "# note\n" + self.BASE
        assert not noop(path, self.BASE, commented)


class TestPython:
    BASE = '#!/usr/bin/env python3\n"""Doc."""\n\n\ndef f(x):\n    return x + 1\n'

    def test_comments_and_formatting_are_a_noop(self):
        changed = self.BASE.replace("return x + 1", "# add one\n    return (x + 1)")
        assert noop("ansible/scripts/tool.py", self.BASE, changed)

    CODED = "# -*- coding: utf-8 -*-\n" + BASE

    @pytest.mark.parametrize(
        ("before", "after"),
        [
            pytest.param(BASE, BASE.replace("x + 1", "x + 2"), id="code"),
            pytest.param(BASE, BASE.replace("Doc.", "Other."), id="docstring"),
            pytest.param(BASE, BASE.replace("python3", "python"), id="shebang"),
            pytest.param(CODED, CODED.replace("utf-8", "latin-1"), id="coding-declaration"),
            pytest.param(BASE, "def f(:\n", id="syntax-error"),
        ],
    )
    def test_a_change_beyond_comments_and_formatting_is_real(self, before, after):
        assert not noop("ansible/scripts/tool.py", before, after)


class TestToml:
    BASE = '[project]\nname = "x"\ndependencies = ["a>=1"]\n'

    def test_comment_only_is_a_noop_and_value_change_is_real(self):
        assert noop("pyproject.toml", self.BASE, "# note\n" + self.BASE)
        assert not noop("pyproject.toml", self.BASE, self.BASE.replace("a>=1", "a>=2"))

    PYPROJECT = (
        '[project]\nname = "x"\ndependencies = ["a>=1"]\n\n[dependency-groups]\ndev = ["pytest"]\n\n[tool.uv]\npackage = false\n\n'
        '[tool.ruff]\nline-length = 160\n\n[tool.ruff.lint]\nselect = ["E"]\n\n[tool.ruff.lint.per-file-ignores]\n"a/**" = ["S101"]\n'
    )

    @pytest.mark.parametrize(
        "change",
        [
            pytest.param("line-length = 100", id="line-length"),
            pytest.param('select = ["E", "F"]', id="lint-select"),
            pytest.param('"a/**" = ["S101", "S105"]', id="per-file-ignores"),
        ],
    )
    def test_ruff_tables_are_ignored_in_pyproject(self, change):
        edited = self.PYPROJECT.replace("line-length = 160", change) if "line-length" in change else self.PYPROJECT
        if "select" in change:
            edited = self.PYPROJECT.replace('select = ["E"]', change)
        if "a/**" in change:
            edited = self.PYPROJECT.replace('"a/**" = ["S101"]', change)
        assert noop("pyproject.toml", self.PYPROJECT, edited)

    def test_ruff_table_added_or_removed_is_a_noop(self):
        without = self.PYPROJECT[: self.PYPROJECT.index("[tool.ruff]")]
        assert noop("pyproject.toml", self.PYPROJECT, without)
        assert noop("pyproject.toml", without, self.PYPROJECT)

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            pytest.param('dependencies = ["a>=1"]', 'dependencies = ["a>=2"]', id="dependencies"),
            pytest.param('dev = ["pytest"]', 'dev = ["pytest", "molecule"]', id="dependency-group"),
            pytest.param("package = false", "package = true", id="uv-package"),
            pytest.param('name = "x"', 'name = "y"', id="project-name"),
        ],
    )
    def test_every_other_pyproject_table_is_real(self, old, new):
        assert not noop("pyproject.toml", self.PYPROJECT, self.PYPROJECT.replace(old, new))

    def test_a_new_tool_table_is_real(self):
        assert not noop("pyproject.toml", self.PYPROJECT, self.PYPROJECT + '\n[tool.pytest.ini_options]\naddopts = "-q"\n')

    def test_ruff_change_alongside_a_dependency_change_is_real(self):
        edited = self.PYPROJECT.replace("line-length = 160", "line-length = 100").replace("a>=1", "a>=2")
        assert not noop("pyproject.toml", self.PYPROJECT, edited)

    def test_the_real_pyproject_has_the_tables_this_relies_on(self):
        data = tomllib.loads((ms.REPO_ROOT / "pyproject.toml").read_text())
        assert "ruff" in data["tool"]
        assert "uv" in data["tool"]

    def test_uv_lock_is_eligible_and_other_toml_is_not(self):
        assert noop("uv.lock", self.BASE, "# note\n" + self.BASE)
        assert not noop("other.toml", self.BASE, "# note\n" + self.BASE)


class TestNeverNoop:
    def test_added_deleted_and_byte_identical_files_are_real(self):
        assert not sd.is_noop_change(TASKS, None, b"a: 1\n")
        assert not sd.is_noop_change(TASKS, b"a: 1\n", None)
        # Same bytes means only the mode (or type) changed.
        assert not sd.is_noop_change(TASKS, b"a: 1\n", b"a: 1\n")

    def test_undecodable_bytes_are_real(self):
        assert not sd.is_noop_change(TASKS, b"\xff\xfe", b"\xff\xfe# c")


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.base = ""

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


@pytest.fixture
def repo(root):
    repo = Repo(root)
    for role in ("alpha", "beta"):
        repo.write(f"ansible/roles/{role}/molecule/default/molecule.yml", "provisioner:\n  name: ansible\n")
        repo.write(f"ansible/roles/{role}/molecule/default/converge.yml", "- hosts: all\n")
        repo.write(f"ansible/roles/{role}/tasks/main.yaml", "- ansible.builtin.debug:\n    msg: hi\n")
    repo.write("ansible/roles/molecule_helpers/tasks/orphan.yaml", "- ansible.builtin.debug:\n    msg: hi\n")
    repo.write("pyproject.toml", '[project]\nname = "x"\n')
    repo.write("ansible/roles/alpha/templates/app.conf.j2", "listen 80;\n")
    repo.git("init", "-q")
    repo.base = repo.commit("base")
    return repo


@pytest.fixture
def queued(repo, monkeypatch):
    def run() -> str:
        head = repo.commit("change")
        out = repo.root / "out.txt"
        monkeypatch.setattr(ms, "REPO_ROOT", repo.root)
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        assert ms.main([repo.base, head]) == 0
        return out.read_text().strip()

    return run


class TestScopeIntegration:
    """molecule_scope.main against a real git history."""

    @pytest.mark.parametrize(
        ("path", "content", "queued_roles"),
        [
            pytest.param(
                "ansible/roles/alpha/tasks/main.yaml", "# why\n- ansible.builtin.debug:\n    msg: hi  # note\n", "roles=[]", id="comment-only-change-to-a-role"
            ),
            pytest.param("ansible/roles/alpha/tasks/main.yaml", "- ansible.builtin.debug:\n    msg: bye\n", 'roles=["alpha"]', id="real-change-to-a-role"),
            pytest.param("pyproject.toml", '[project]\nname = "x"\n[tool.ruff]\nline-length = 100\n', "roles=[]", id="ruff-only-pyproject-change"),
            pytest.param("pyproject.toml", '# note\n[project]\nname = "x"\n', "roles=[]", id="comment-only-pyproject-change"),
            pytest.param("pyproject.toml", '[project]\nname = "y"\n', 'roles=["alpha","beta"]', id="real-pyproject-change"),
            pytest.param(
                "ansible/roles/molecule_helpers/tasks/orphan.yaml",
                "# note\n- ansible.builtin.debug:\n    msg: hi\n",
                "roles=[]",
                id="comment-only-change-to-an-unreferenced-helper",
            ),
            pytest.param(
                "ansible/roles/alpha/templates/app.conf.j2", "# listen\nlisten 80;\n", 'roles=["alpha"]', id="comment-in-a-file-ansible-ships-as-content"
            ),
        ],
    )
    def test_one_changed_file_queues_the_roles_it_affects(self, repo, queued, path, content, queued_roles):
        repo.write(path, content)
        assert queued() == queued_roles

    def test_comment_and_real_change_together_queue_only_for_the_real_one(self, repo, queued):
        repo.write("ansible/roles/alpha/tasks/main.yaml", "# why\n- ansible.builtin.debug:\n    msg: hi\n")
        repo.write("ansible/roles/beta/tasks/main.yaml", "- ansible.builtin.debug:\n    msg: bye\n")
        assert queued() == 'roles=["beta"]'

    def test_added_and_deleted_files_are_real_changes(self, repo, queued):
        repo.write("ansible/roles/beta/tasks/new.yaml", "# only a comment\n")
        (repo.root / "ansible/roles/alpha/tasks/main.yaml").unlink()
        assert queued() == 'roles=["alpha","beta"]'

    def test_mode_only_change_is_a_real_change(self, repo, queued):
        (repo.root / "ansible/roles/alpha/tasks/main.yaml").chmod(0o755)
        assert queued() == 'roles=["alpha"]'


class TestRealTree:
    def test_real_role_task_files_are_eligible_and_fixtures_are_not(self):
        base = b"- ansible.builtin.debug:\n    msg: hi\n"
        assert sd.is_noop_change("ansible/roles/compose/tasks/init.yaml", base, b"# c\n" + base)
        fixture = "ansible/roles/molecule_helpers/fixtures/generic_alpine_app/compose.yaml"
        assert not sd.is_noop_change(fixture, base, b"# c\n" + base)

    def test_every_eligible_yaml_pattern_matches_a_real_file(self, subtests):
        root = ms.REPO_ROOT
        files = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts]
        for pattern in sd.ELIGIBLE_YAML:
            with subtests.test(pattern=pattern.pattern):
                assert any(pattern.match(f) for f in files)
