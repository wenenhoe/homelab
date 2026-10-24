"""A throwaway git repository the progress log is generated from, and helpers to read what comes out."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT_DATE = "2026-10-05T09:00:00+0800"
IDENTITY = ("-c", "user.name=Test", "-c", "user.email=test@example.invalid")


class Repo:
    """A repository on `main` where each change lands as a PR merge, the way the real one does."""

    def __init__(self, path: Path):
        self.path = path
        self.git("init", "-q", "-b", "main")
        self.root = self.direct("chore: start", {"README.md": "start\n"}, ROOT_DATE)

    def git(self, *args: str, when: str | None = None) -> str:
        env = {**os.environ}
        if when:
            env |= {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        result = subprocess.run(["git", "-C", str(self.path), *IDENTITY, *args], capture_output=True, text=True, env=env, check=True)
        return result.stdout.strip()

    def write(self, files: dict[str, str | None]) -> None:
        for name, text in files.items():
            target = self.path / name
            if text is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)

    def direct(self, subject: str, files: dict[str, str | None], when: str) -> str:
        """A commit straight on `main`, as before the PR workflow."""
        self.write(files)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", subject, when=when)
        return self.git("rev-parse", "HEAD")

    def pr(self, number: int, branch: str, title: str, files: dict[str, str | None], when: str) -> str:
        """A PR merge: a commit on `branch`, merged with a merge commit whose body is the PR title."""
        self.git("checkout", "-q", "-b", branch)
        self.write(files)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", title, when=when)
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", f"Merge pull request #{number} from wenenhoe/{branch}", "-m", title, branch, when=when)
        self.git("branch", "-q", "-D", branch)
        return self.git("rev-parse", "HEAD")


def project_doc(status: str) -> str:
    return f"---\nid: PROJ-x\nstatus: {status}\n---\n\n# X\n"


def snapshot(directory: Path) -> dict[str, bytes]:
    """Every file under a directory, by relative path."""
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in sorted(directory.rglob("*")) if path.is_file()}


def project_path(slug: str) -> str:
    """Built, not written out: a literal path to a project doc that doesn't exist fails the docs drift check."""
    return f"docs/projects/{slug}.md"


def decision_path(number: str, slug: str) -> str:
    return f"docs/decisions/{number}-{slug}/revision-000.md"
