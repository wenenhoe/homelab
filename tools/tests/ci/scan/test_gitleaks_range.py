"""Tests for ci.scan.gitleaks_range.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest
from ci.scan import gitleaks_range as gr

CONFIG_TEXT = """\
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.1
    hooks:
      - id: gitleaks
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
"""


def make_cache(cache: Path, rows: list[tuple[str, str, str]]) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cache / "db.db")
    conn.execute("CREATE TABLE repos (repo TEXT NOT NULL, ref TEXT NOT NULL, path TEXT NOT NULL, PRIMARY KEY (repo, ref))")
    conn.executemany("INSERT INTO repos VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def make_binary(repo_dir: Path, env: str = "system") -> Path:
    path = repo_dir / f"golangenv-{env}/bin/gitleaks"
    path.parent.mkdir(parents=True)
    path.write_text("")
    return path


class TestPinnedRev:
    def test_reads_the_rev_that_follows_the_gitleaks_repo(self):
        assert gr.pinned_rev(CONFIG_TEXT) == "v8.30.1"

    def test_a_config_without_gitleaks_is_an_error(self):
        with pytest.raises(gr.GitleaksUnavailableError):
            gr.pinned_rev("repos:\n  - repo: https://github.com/pre-commit/pre-commit-hooks\n    rev: v6.0.0\n")


class TestCacheDir:
    def test_pre_commit_home_wins(self):
        assert gr.cache_dir({"PRE_COMMIT_HOME": "/p", "XDG_CACHE_HOME": "/x", "HOME": "/h"}) == Path("/p")

    def test_xdg_cache_home_is_next(self):
        assert gr.cache_dir({"XDG_CACHE_HOME": "/x", "HOME": "/h"}) == Path("/x/pre-commit")

    def test_home_cache_is_the_default(self):
        assert gr.cache_dir({"HOME": "/h"}) == Path("/h/.cache/pre-commit")


class TestBinary:
    def test_finds_the_build_for_the_pinned_rev(self, root):
        old = root / "repo-old"
        new = root / "repo-new"
        make_binary(old)
        expected = make_binary(new)
        make_cache(root / "cache", [(gr.GITLEAKS_REPO, "v8.29.0", str(old)), (gr.GITLEAKS_REPO, "v8.30.1", str(new))])
        assert gr.binary(root / "cache", "v8.30.1") == expected

    @pytest.mark.parametrize("env", ["system", "default"])
    def test_finds_the_binary_whichever_go_pre_commit_used(self, root, env):
        expected = make_binary(root / "repo", env)
        make_cache(root / "cache", [(gr.GITLEAKS_REPO, "v8.30.1", str(root / "repo"))])
        assert gr.binary(root / "cache", "v8.30.1") == expected

    def test_no_cache_is_an_error(self, root):
        with pytest.raises(gr.GitleaksUnavailableError, match="no pre-commit cache"):
            gr.binary(root / "cache", "v8.30.1")

    def test_a_rev_that_was_never_installed_is_an_error(self, root):
        make_cache(root / "cache", [(gr.GITLEAKS_REPO, "v8.29.0", str(root / "repo-old"))])
        with pytest.raises(gr.GitleaksUnavailableError, match=r"v8\.30\.1 is not in the pre-commit cache"):
            gr.binary(root / "cache", "v8.30.1")

    def test_an_installed_repo_without_the_binary_is_an_error(self, root):
        make_cache(root / "cache", [(gr.GITLEAKS_REPO, "v8.30.1", str(root / "repo"))])
        with pytest.raises(gr.GitleaksUnavailableError, match="no gitleaks binary"):
            gr.binary(root / "cache", "v8.30.1")


class TestCommand:
    def test_scans_the_commits_between_base_and_head_with_redaction(self):
        assert gr.command(Path("/b/gitleaks"), "aaa", "bbb") == ["/b/gitleaks", "git", "--redact", "--verbose", "--no-banner", "--log-opts=aaa..bbb", "."]


class TestMain:
    @pytest.fixture
    def tree(self, root):
        (root / ".config").mkdir()
        (root / ".config/.pre-commit-config.yaml").write_text(CONFIG_TEXT)
        repo = root / "hook-repo"
        binary = make_binary(repo)
        make_cache(root / "cache", [(gr.GITLEAKS_REPO, "v8.30.1", str(repo))])
        return root, binary

    @pytest.mark.parametrize("returncode", [0, 1])
    def test_returns_what_gitleaks_returned_and_runs_it_at_the_repo_root(self, tree, returncode):
        root, binary = tree
        calls = []

        def runner(args, cwd, capture):
            calls.append((args, cwd, capture))
            return subprocess.CompletedProcess(args, returncode)

        assert gr.main(["aaa", "bbb"], runner, root, {"PRE_COMMIT_HOME": str(root / "cache")}) == returncode
        assert calls == [(gr.command(binary, "aaa", "bbb"), root, False)]

    def test_a_missing_build_fails_without_running_anything(self, root, capsys):
        (root / ".config").mkdir()
        (root / ".config/.pre-commit-config.yaml").write_text(CONFIG_TEXT)

        def runner(args, cwd, capture):
            raise AssertionError("nothing should run")

        assert gr.main(["aaa", "bbb"], runner, root, {"PRE_COMMIT_HOME": str(root / "cache")}) == 1
        assert "::error::" in capsys.readouterr().err
