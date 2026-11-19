"""`gh` calls for this tool, through `land_series.run`, so a missing program, a hung one and a failing one are told apart as they are there."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from land_series.land import TRANSIENT_MARKERS
from land_series.run import CommandError, CommandFailed, TimedOut, checked

GH_TIMEOUT_SECONDS = 120.0
READ_ATTEMPTS = 3
READ_RETRY_SECONDS = 2.0


class GhError(Exception):
    """A `gh` call failed; the message says what it printed."""


def _transient(error: CommandError) -> bool:
    if isinstance(error, TimedOut):
        return True
    return isinstance(error, CommandFailed) and any(marker in error.output.lower() for marker in TRANSIENT_MARKERS)


def read(repo: Path, *args: str, sleep: Callable[[float], None] = time.sleep) -> str:
    """A `gh` call that only reads, tried again after a growing pause when it failed the way a dropped connection does."""
    for attempt in range(1, READ_ATTEMPTS + 1):
        try:
            return checked(["gh", *args], cwd=repo, timeout=GH_TIMEOUT_SECONDS).text
        except CommandError as error:
            if attempt == READ_ATTEMPTS or not _transient(error):
                raise GhError(str(error)) from error
            sleep(READ_RETRY_SECONDS * attempt)
    raise AssertionError("unreachable: the last attempt returns or raises")


def change(repo: Path, *args: str) -> str:
    """A `gh` call that changes something, so it is never repeated."""
    try:
        return checked(["gh", *args], cwd=repo, timeout=GH_TIMEOUT_SECONDS).text
    except CommandError as error:
        raise GhError(" ".join(str(error).split())) from error
