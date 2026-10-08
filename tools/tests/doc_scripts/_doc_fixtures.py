"""Builders for throwaway docs/ trees used by the doc-tooling tests.
Real frontmatter, real files on disk - the code under test reads paths,
so nothing here is mocked.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
from pathlib import Path
from types import ModuleType

import yaml


def write_doc(root: Path, rel: str, fm: dict, body: str = "# Title\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{body}", encoding="utf-8")
    return path


def revision(root: Path, lineage: str, number: int, body: str = "# Title\n", letter: str | None = None, **overrides) -> Path:
    """`lineage` is the directory name, e.g. '0013-secret-storage'. `letter` makes it a
    competing candidate (revision-NNN-x.md, with a matching `candidate:` unless overridden)."""
    fm = {
        "id": f"ADR-{lineage[:4]}",
        "revision": number,
        "type": "adr",
        "title": "Secret storage",
        "short": lineage,
        "solution": f"Solution {number}",
        "summary": "Where secrets live.",
        "topic": "secrets-store",
        "status": "working",
    }
    if letter:
        fm["candidate"] = letter
    fm.update(overrides)
    suffix = f"-{letter}" if letter else ""
    return write_doc(root, f"docs/decisions/{lineage}/revision-{number:03d}{suffix}.md", fm, body)


def project(root: Path, name: str, **overrides) -> Path:
    fm = {"id": f"PROJ-{name}", "title": name, "type": "project", "status": "not-started", "summary": f"{name} summary"}
    fm.update(overrides)
    return write_doc(root, f"docs/projects/{name}.md", fm)


def assert_one_error(errors: list[str], *fragments: str) -> None:
    assert len(errors) == 1, errors
    for fragment in fragments:
        assert fragment in errors[0], f"{fragment!r} not in {errors[0]!r}"


class GitRepo:
    """A throwaway git repository at `root`, and the CLI under test run against it."""

    def __init__(self, root: Path, cli: ModuleType) -> None:
        self.root = root
        self.cli = cli

    def git(self, *args: str) -> str:
        cmd = ["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t.t", "-c", "commit.gpgsign=false", *args]
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def branch(self, name: str = "feature") -> None:
        self.git("checkout", "-q", "-b", name)

    def run_cli(self, *args: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.cli.main([*args, "--root", str(self.root)])
        return code, out.getvalue() + err.getvalue()

    def pr(self) -> tuple[int, str]:
        return self.run_cli("--base", "main", "--head", "feature")
