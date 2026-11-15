"""Tests for ci.timing.fingerprint.

The digest is over what `git ls-files -s` lists, so the tests run on small
temporary repositories and the real tree is checked for the roles it names.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from ci.proc import run
from ci.scope import molecule_scope
from ci.timing import fingerprint


def write(root: Path, path: str, text: str = "---\n") -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def stage(root: Path) -> None:
    git(root, "add", "--all")


@pytest.fixture
def repo(root):
    git(root, "init", "--quiet")
    for role in ("a", "b"):
        write(root, f"ansible/roles/{role}/molecule/default/molecule.yml")
        write(root, f"ansible/roles/{role}/tasks/main.yaml", "- debug: {msg: hi}\n")
    write(root, "ansible/roles/a/defaults/main.yaml", "x: 1\n")
    write(root, "ansible/requirements.yml", "collections: []\n")
    stage(root)
    return root


class TestFingerprints:
    def test_every_role_with_scenarios_has_one_and_a_role_without_does_not(self, repo):
        write(repo, "ansible/roles/plain/tasks/main.yaml")
        stage(repo)
        assert sorted(fingerprint.fingerprints(repo)) == ["a", "b"]

    def test_the_same_files_give_the_same_digest_on_every_call(self, repo):
        assert fingerprint.fingerprints(repo) == fingerprint.fingerprints(repo)

    def test_a_change_inside_a_role_changes_that_role_and_no_other(self, repo):
        before = fingerprint.fingerprints(repo)
        write(repo, "ansible/roles/a/defaults/main.yaml", "x: 2\n")
        stage(repo)
        after = fingerprint.fingerprints(repo)
        assert after["a"] != before["a"]
        assert after["b"] == before["b"]

    def test_a_new_file_in_a_role_changes_it(self, repo):
        before = fingerprint.fingerprints(repo)
        write(repo, "ansible/roles/b/handlers/main.yaml")
        stage(repo)
        assert fingerprint.fingerprints(repo)["b"] != before["b"]

    def test_a_path_every_scenario_inherits_changes_every_role(self, repo):
        before = fingerprint.fingerprints(repo)
        write(repo, "ansible/requirements.yml", "collections: [x]\n")
        stage(repo)
        after = fingerprint.fingerprints(repo)
        assert after["a"] != before["a"]
        assert after["b"] != before["b"]

    def test_a_file_outside_every_watch_set_changes_nothing(self, repo):
        before = fingerprint.fingerprints(repo)
        write(repo, "docs/readme.md", "words\n")
        stage(repo)
        assert fingerprint.fingerprints(repo) == before

    def test_a_role_another_role_runs_is_part_of_its_fingerprint(self, repo):
        write(repo, "ansible/roles/a/molecule/default/converge.yml", "- hosts: all\n  roles: [b]\n")
        stage(repo)
        before = fingerprint.fingerprints(repo)
        write(repo, "ansible/roles/b/tasks/main.yaml", "- debug: {msg: changed}\n")
        stage(repo)
        assert fingerprint.fingerprints(repo)["a"] != before["a"]

    def test_a_file_that_is_not_tracked_does_not_count(self, repo):
        before = fingerprint.fingerprints(repo)
        write(repo, "ansible/roles/a/defaults/untracked.yaml")
        assert fingerprint.fingerprints(repo) == before

    def test_a_list_of_paths_longer_than_one_call_is_still_one_digest(self, repo, monkeypatch):
        whole = fingerprint.fingerprints(repo)
        monkeypatch.setattr(fingerprint, "CHUNK", 1)
        assert fingerprint.fingerprints(repo) == whole

    def test_git_failing_is_an_error_not_an_empty_digest(self, repo):
        def failing(args, cwd, capture):
            result = run(args, cwd, capture)
            result.returncode = 128
            return result

        with pytest.raises(fingerprint.FingerprintError, match="git ls-files exited 128"):
            fingerprint.fingerprints(repo, failing)


def test_the_real_tree_has_a_fingerprint_for_each_role_with_scenarios():
    assert sorted(fingerprint.fingerprints(molecule_scope.REPO_ROOT)) == molecule_scope.role_names(molecule_scope.REPO_ROOT)
