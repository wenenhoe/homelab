"""A real git repository standing in for the remote the CD agent fetches from.

Nothing here is mocked: the code under test runs real `git fetch` against it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# What a job's command does inside the checkout, so a test can read back from
# the log what ran, on which tree. STRAY makes it leave an edit and an
# untracked file behind; EXIT sets its exit status.
JOB_SCRIPT = """\
import os
import pathlib

here = pathlib.Path()
payload = here.joinpath("payload.txt").read_text().strip()
stray = here.joinpath("stray.txt").exists()
with open(os.environ["CD_AGENT_TEST_LOG"], "a") as log:
    log.write(f"payload={payload} stray={stray} cwd={here.resolve().name}\\n")
if os.environ.get("CD_AGENT_TEST_STRAY"):
    here.joinpath("stray.txt").write_text("left behind")
    here.joinpath("payload.txt").write_text("edited")
raise SystemExit(int(os.environ.get("CD_AGENT_TEST_EXIT", "0")))
"""


class Origin:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.git("init", "-q", "-b", "main")

    @property
    def url(self) -> str:
        return f"file://{self.path}"

    def git(self, *args: str) -> str:
        identity = ["-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]
        return subprocess.run(["git", "-C", str(self.path), *identity, *args], check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, payload: str, branch: str = "main", files: dict[str, str] | None = None) -> str:
        """Commit `payload` (and any extra files) on `branch`, which starts from main; return the commit id."""
        if branch != "main":
            self.git("checkout", "-q", "-B", branch, "main")
        for name, text in {"job.py": JOB_SCRIPT, "payload.txt": payload + "\n", **(files or {})}.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", payload)
        commit = self.git("rev-parse", "HEAD")
        if branch != "main":
            self.git("checkout", "-q", "main")
        return commit
