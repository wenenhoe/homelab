"""Real git repositories for the deliver_series tests: an upstream holding `main`, and a working clone whose commits are delivered."""

from __future__ import annotations

import subprocess
from pathlib import Path

MAINTAINER = ("Maint Ainer", "maint@example.invalid")
BOT = ("renovate[bot]", "bot@example.invalid")
SESSION = ("Claude", "noreply@anthropic.com")
GOOD_DATE = "2026-11-28T10:00:00+0800"
TRAILER = "Co-Authored-By: Test Model <noreply@anthropic.com>"


def message(subject: str, *trailers: str) -> str:
    """A commit message: the subject, a body paragraph, and the trailers (the model's by default)."""
    return "\n\n".join([subject, "Say what changed.", "\n".join(trailers or (TRAILER,))])


def git(path: Path, *args: str, identity: tuple[str, str] = MAINTAINER, committer: tuple[str, str] = SESSION, date: str = GOOD_DATE) -> str:
    env = {
        "GIT_AUTHOR_NAME": identity[0],
        "GIT_AUTHOR_EMAIL": identity[1],
        "GIT_COMMITTER_NAME": committer[0],
        "GIT_COMMITTER_EMAIL": committer[1],
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
        "HOME": str(path),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    done = subprocess.run(["git", "-C", str(path), "-c", "commit.gpgsign=false", *args], env=env, capture_output=True, check=True)
    return done.stdout.decode().strip()


def commit(
    path: Path,
    text: str,
    files: dict[str, str | bytes],
    identity: tuple[str, str] = MAINTAINER,
    date: str = GOOD_DATE,
    committer: tuple[str, str] = SESSION,
) -> str:
    """Commit `files` (path to content) with the message `text`."""
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", text, identity=identity, committer=committer, date=date)
    return git(path, "rev-parse", "HEAD")


class Workspace:
    """`upstream` is the remote `origin` of `work`; `main` there holds a maintainer's commit and then a bot's."""

    def __init__(self, root: Path) -> None:
        self.upstream = root / "upstream"
        self.work = root / "work"
        self.out = root / "out"
        self.out.mkdir()
        self.upstream.mkdir()
        git(self.upstream, "init", "-q", "-b", "main")
        commit(self.upstream, "chore: start", {"base.txt": "base\n"})
        commit(self.upstream, "chore(deps): update a pin", {"pin.txt": "1\n"}, identity=BOT)
        git(root, "clone", "-q", str(self.upstream), "work")
        self.count = 0

    def commit(
        self,
        subject: str,
        text: str | None = None,
        files: dict[str, str | bytes] | None = None,
        identity: tuple[str, str] = MAINTAINER,
        date: str = GOOD_DATE,
        committer: tuple[str, str] = SESSION,
    ) -> str:
        """A commit in the working clone with the commit form, unless an argument changes it; each commit gets a file of its own."""
        self.count += 1
        return commit(self.work, text or message(subject), files or {f"file{self.count}.txt": subject}, identity, date, committer)
