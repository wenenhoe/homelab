"""The command line: the footer's commit and date come from the repository, and a build is written into an empty directory."""

from __future__ import annotations

import subprocess

import pytest
from doc_site import __main__ as cli
from doc_site import site


@pytest.fixture
def repository(tmp_path, monkeypatch):
    """A one-commit repository the command reads its commit from; yields the commit id."""
    env = {"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@example.com", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@example.com"}
    env |= {"GIT_COMMITTER_DATE": "2026-11-21T16:12:00+0800", "GIT_AUTHOR_DATE": "2026-11-21T16:12:00+0800", "PATH": "/usr/bin:/bin"}
    run = lambda *args: subprocess.run(["git", "-C", str(tmp_path), *args], env=env, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    run("init", "-q")
    run("commit", "-q", "--allow-empty", "-m", "x")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    return run("rev-parse", "HEAD")


def test_the_stamp_is_the_commit_and_its_date(repository):
    assert cli.stamp_of(repository) == site.Stamp(repository, "2026-11-21T16:12:00+08:00")


def test_a_commit_the_repository_lacks_is_refused(repository):
    with pytest.raises(SystemExit, match="is not a commit"):
        cli.stamp_of("0" * 40)


@pytest.mark.parametrize("commit", ["main", "HEAD", "abc1234", "--output=x"])
def test_only_a_full_commit_id_is_passed_to_git(commit):
    with pytest.raises(SystemExit, match="full 40-character"):
        cli.stamp_of(commit)
