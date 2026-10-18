"""Real local git repositories standing in for GitHub, for the tests of the shell-test pins."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# The identity is set per command and the user's and system's git config are not read, so a test runs the same anywhere.
_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, env=_ENV, capture_output=True, text=True, check=True)
    return done.stdout.strip()


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True)
        git(path, "init", "--quiet", "-b", "main")
        self._count = 0

    def commit(self) -> str:
        """A new commit on the current branch; its SHA."""
        self._count += 1
        (self.path / "file.txt").write_text(f"{self._count}\n")
        git(self.path, "add", "file.txt")
        git(self.path, "commit", "--quiet", "-m", f"commit {self._count}")
        return git(self.path, "rev-parse", "HEAD")

    def tag(self, name: str, *, annotated: bool, at: str = "HEAD") -> None:
        """Create or move a tag. An annotated one is a tag object that points at the commit."""
        args = ["-m", f"release {name}"] if annotated else []
        git(self.path, "tag", "--force", *args, name, at)

    def tag_object(self, name: str) -> str:
        """The SHA of the tag itself, which for an annotated tag is not its commit's."""
        return git(self.path, "rev-parse", f"refs/tags/{name}")

    def branch(self, name: str) -> None:
        git(self.path, "branch", name)


class Remote:
    """A directory of repositories named as GitHub names them: `owner/name`, reached at `base`."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.base = f"{root.as_uri()}/"

    def repo(self, repository: str) -> Repo:
        return Repo(self.root / f"{repository}.git")
