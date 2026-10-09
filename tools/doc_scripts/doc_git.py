"""Reading a change's base out of git, shared by check_project_scope.py and
check_project_close.py so both read the base the same way. Not a standalone
script.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def file_at(root: Path, ref: str, path: str) -> str | None:
    """The file's text at `ref` (`""` is the index), or None if it doesn't exist there."""
    try:
        return git(root, "show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return None


def base_project_loader(root: Path, ref: str):
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
