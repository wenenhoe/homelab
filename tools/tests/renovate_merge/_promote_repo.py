"""A bare remote with `main` and `maintenance`, and a clone of it made before anything is pushed, so the code under test has to fetch what it reads."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

IDENTITY = ["-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false"]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *IDENTITY, *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@dataclass
class Remote:
    bare: Path
    builder: Path
    clone: Path
    _files: int = 0

    def _commit(self, message: str) -> None:
        self._files += 1
        (self.builder / f"file-{self._files}.txt").write_text(message)
        git(self.builder, "add", ".")
        git(self.builder, "commit", "-q", "-m", message)

    def commit(self, branch: str, message: str) -> None:
        """A commit made straight on `branch`, as a push by Renovate's app or the maintainer makes one."""
        git(self.builder, "checkout", "-q", branch)
        self._commit(message)

    def merge_pull(self, number: int, head: str, into: str = "maintenance") -> None:
        """A pull request merged into `into`, with the merge commit GitHub makes."""
        git(self.builder, "checkout", "-q", "-b", head, into)
        self._commit(f"change for {head}")
        git(self.builder, "checkout", "-q", into)
        git(self.builder, "merge", "-q", "--no-ff", "-m", f"Merge pull request #{number} from wenenhoe/{head}\n\nbody", head)

    def sync(self, branch: str, source: str = "main") -> None:
        """`source` merged into `branch`, as the realignment before a Renovate run does."""
        git(self.builder, "checkout", "-q", branch)
        git(self.builder, "merge", "-q", "--no-ff", "-m", f"Merge branch '{source}' into {branch}", source)

    def push(self) -> None:
        git(self.builder, "push", "-q", "origin", "main", "maintenance")


def make_remote(tmp_path: Path) -> Remote:
    bare, builder, clone = tmp_path / "remote.git", tmp_path / "builder", tmp_path / "clone"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(tmp_path, "clone", "-q", str(bare), str(builder))
    git(builder, "checkout", "-q", "-b", "main")
    remote = Remote(bare, builder, clone)
    remote._commit("initial")
    git(builder, "branch", "maintenance")
    git(builder, "push", "-q", "origin", "main", "maintenance")
    git(tmp_path, "clone", "-q", str(bare), str(clone))
    return remote
