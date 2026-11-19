"""Reading a change's base out of git, shared by check_project_scope.py and
check_project_close.py so both read the base the same way. Not a standalone
script.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import yaml


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


@contextmanager
def checkout(root: Path, rev: str) -> Iterator[Path]:
    """A detached checkout of `rev` in a temporary directory, for a rule that reads files from disk: it then reads the
    tree it judges, not the one the hook happens to run in."""
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "tree"
        git(root, "worktree", "add", "--detach", "--quiet", str(tree), rev)
        try:
            yield tree
        finally:
            git(root, "worktree", "remove", "--force", str(tree))


def file_at(root: Path, ref: str, path: str) -> str | None:
    """The file's text at `ref` (`""` is the index), or None if it doesn't exist there."""
    try:
        return git(root, "show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return None


def git_grep_files(root: Path, ref: str, term: str) -> list[str]:
    """The text files at `ref` that contain `term`, as repo-relative paths (git grep exits 1 for none)."""
    done = subprocess.run(["git", "-C", str(root), "grep", "-l", "-z", "-I", "-F", "-e", term, ref], check=False, capture_output=True, text=True)
    if done.returncode > 1:
        raise SystemExit(f"git grep failed: {done.stderr.strip()}")
    return [item.removeprefix(f"{ref}:") for item in done.stdout.split("\0") if item]


def base_frontmatter_loader(root: Path, ref: str):
    """`load(path)` returns the frontmatter of any doc as it stood at `ref`, or None."""

    def load(path: str) -> dict | None:
        text = file_at(root, ref, path)
        if text is None:
            return None  # the doc didn't exist on the base
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not m:
            return None
        try:
            data = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            return None
        return data if isinstance(data, dict) else None

    return load
