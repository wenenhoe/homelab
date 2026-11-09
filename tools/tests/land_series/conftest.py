"""Fixtures for the land_series tests."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from _series_repo import Author, Repo, git


@pytest.fixture
def repo(tmp_path_factory: pytest.TempPathFactory) -> Repo:
    """A repository whose `main` the layers are replayed on."""
    return Repo(tmp_path_factory.mktemp("repo"))


@pytest.fixture
def author(repo: Repo, tmp_path_factory: pytest.TempPathFactory) -> Author:
    return Author(repo, tmp_path_factory.mktemp("author") / "clone")


@dataclass
class FakeGitHub:
    """The remote `origin` (a bare repository) and the `gh` on PATH that merges into it."""

    remote: Path
    state_file: Path

    def state(self) -> dict:
        return json.loads(self.state_file.read_text())

    def calls(self, *verb: str) -> list[list[str]]:
        return [call for call in self.state()["calls"] if call[: len(verb)] == list(verb)]

    def branches(self) -> list[str]:
        return git(self.remote, "for-each-ref", "--format=%(refname:short)", "refs/heads").split()

    def merges_on(self, branch: str) -> list[str]:
        return git(self.remote, "log", "--first-parent", "--merges", "--format=%s", branch).splitlines()

    def merges_on_main(self) -> list[str]:
        return self.merges_on("main")

    def file_on_main(self, name: str) -> str:
        return git(self.remote, "show", f"main:{name}")


@pytest.fixture
def github(repo: Repo, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    """`repo` with a remote `origin` holding its `main`, and a fake `gh` first on PATH that merges pull requests into that remote."""
    remote = tmp_path_factory.mktemp("remote")
    git(remote, "init", "-q", "--bare", "-b", "main")
    git(repo.path, "remote", "add", "origin", str(remote))
    git(repo.path, "push", "-q", "origin", "main")
    git(repo.path, "fetch", "-q", "origin")
    bin_dir = tmp_path_factory.mktemp("bin")
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\nexec {sys.executable} {Path(__file__).parent / "fake_gh.py"} "$@"\n')
    gh.chmod(0o755)
    state_file = tmp_path_factory.mktemp("gh-state") / "state.json"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_STATE", str(state_file))
    monkeypatch.setenv("FAKE_GH_REMOTE", str(remote))
    monkeypatch.setenv("FAKE_GH_CHECKS", "pass")
    return FakeGitHub(remote, state_file)
