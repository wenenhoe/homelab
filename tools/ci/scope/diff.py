"""Reading a PR's diff and file contents from git."""

from __future__ import annotations

import subprocess
from pathlib import Path


class DiffError(Exception):
    """git couldn't produce the diff."""


def changed_files(root: Path, base: str, head: str) -> list[str]:
    # --no-renames lists both sides of a rename, so a file moved out of a
    # watched path still counts as touching it.
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", base, head],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DiffError(f"git diff failed: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]


def read_at(root: Path, rev: str, path: str) -> bytes | None:
    """`path` as of `rev`, or None if it doesn't exist there."""
    result = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True, check=False)
    return result.stdout if result.returncode == 0 else None
