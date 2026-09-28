"""Running external commands, in a form tests can replace."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

# (args, cwd, capture) -> result. capture=False lets the child write
# straight to this process's stdout/stderr so a long run streams into the
# job log; capture=True returns its stdout for the caller to read.
Runner = Callable[[list[str], Path, bool], "subprocess.CompletedProcess[str]"]


def run(args: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
    if capture:
        return subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, text=True, check=False)
    return subprocess.run(args, cwd=cwd, text=True, check=False)
