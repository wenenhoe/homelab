"""Real git repositories for the land_series tests: a repository holding `main`, and an author clone that writes patches against it.

Nothing is mocked: the code under test runs real `git am`, `git worktree` and `git format-patch`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

IDENTITY = ["-c", "user.name=Test Author", "-c", "user.email=author@example.invalid", "-c", "commit.gpgsign=false"]
FIRST_DAY = 1_700_000_000


def git(path: Path, *args: str, stdin: bytes | None = None) -> str:
    result = subprocess.run(["git", "-C", str(path), *IDENTITY, *args], input=stdin, capture_output=True, check=True)
    return result.stdout.decode().strip()


class Repo:
    """A repository on branch `main` with one commit."""

    def __init__(self, path: Path) -> None:
        self.path = path
        git(path, "init", "-q", "-b", "main")
        (path / "base.txt").write_text("base\n")
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", "chore: start", "--date", f"@{FIRST_DAY}")

    def install_hook(self, name: str, script: str) -> None:
        hook = self.path / ".git" / "hooks" / name
        hook.write_text("#!/bin/sh\n" + script)
        hook.chmod(0o755)

    def worktrees(self) -> list[str]:
        return [line for line in git(self.path, "worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]


class Author:
    """A clone of a repository that writes each patch on top of the one before, as a series is written."""

    def __init__(self, repo: Repo, path: Path) -> None:
        git(path.parent, "clone", "-q", str(repo.path), path.name)
        self.path = path
        self.count = 0

    def patch(self, subject: str, files: dict[str, str]) -> bytes:
        """Commit `files` (path to text) as `subject` and return the `git format-patch` message for that commit."""
        for name, text in files.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        git(self.path, "add", "-A")
        self.count += 1
        git(self.path, "commit", "-q", "-m", subject, "--date", f"@{FIRST_DAY + self.count * 60}")
        return subprocess.run(["git", "-C", str(self.path), "format-patch", "-1", "--stdout"], capture_output=True, check=True).stdout


def series_file(layers: list[tuple[str, bytes]]) -> bytes:
    """A series file: `layers` is (manifest line, patch) pairs in order."""
    manifest = "\n".join(line for line, _ in layers) + "\n\n"
    return manifest.encode() + b"".join(patch for _, patch in layers)
