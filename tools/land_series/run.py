"""The one place `land_series` starts `git` and `gh`, so a missing program, a hung one and a failing one are told apart the same way everywhere."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class CommandError(Exception):
    """A command could not be run to completion."""


class ToolMissing(CommandError):
    """The program is not installed, or is not on PATH."""

    def __init__(self, argv: Sequence[str]) -> None:
        super().__init__(f"`{argv[0]}` is not installed or is not on PATH")


class TimedOut(CommandError):
    """The program was still running when the time allowed for it ended; it was killed."""

    def __init__(self, argv: Sequence[str], seconds: float) -> None:
        super().__init__(f"`{' '.join(argv[:2])}` did not finish within {seconds:g} seconds")


class CommandFailed(CommandError):
    """The program ran and exited non-zero. The argument list, exit code and output are kept so a caller can decide on them, not on the message."""

    def __init__(self, argv: Sequence[str], returncode: int, output: str) -> None:
        super().__init__(f"`{' '.join(argv[:2])}` failed: {output}")
        self.argv = tuple(argv)
        self.returncode = returncode
        self.output = output


@dataclass(frozen=True)
class Completed:
    argv: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes

    @property
    def text(self) -> str:
        """What it printed to stdout."""
        return self.stdout.decode("utf-8", errors="replace").strip()

    @property
    def output(self) -> str:
        """Everything it printed, stdout then stderr."""
        return (self.stdout + self.stderr).decode("utf-8", errors="replace").strip()


def run(
    argv: Sequence[str], *, cwd: Path | None = None, stdin: bytes | None = None, env: dict[str, str] | None = None, timeout: float | None = None
) -> Completed:
    """Run `argv` to completion. A non-zero exit is returned for the caller to read; a program that is missing or too slow raises.

    With no `stdin` the program gets none, so one that would stop to ask a question fails instead of waiting for an answer nobody sees.
    """
    try:
        done = subprocess.run(
            argv,
            cwd=cwd,
            input=stdin,
            stdin=None if stdin is not None else subprocess.DEVNULL,
            capture_output=True,
            check=False,
            env={**os.environ, **env} if env else None,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise ToolMissing(argv) from None
    except subprocess.TimeoutExpired:
        raise TimedOut(argv, timeout or 0) from None
    return Completed(tuple(argv), done.returncode, done.stdout, done.stderr)


def checked(
    argv: Sequence[str], *, cwd: Path | None = None, stdin: bytes | None = None, env: dict[str, str] | None = None, timeout: float | None = None
) -> Completed:
    """`run`, raising `CommandFailed` on a non-zero exit."""
    result = run(argv, cwd=cwd, stdin=stdin, env=env, timeout=timeout)
    if result.returncode != 0:
        raise CommandFailed(argv, result.returncode, result.output)
    return result
