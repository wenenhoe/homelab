"""A few lines on the terminal that are redrawn in place while a check or a CI wait runs and erased when it ends.

Progress that should stay on screen goes through `Progress` as lines; this is for status that is only worth reading while it changes, so
a finished step leaves one line behind instead of a screenful. Nothing is drawn unless the stream is a terminal that handles cursor
movement, so a pipe or a log file receives the progress lines alone.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from typing import TextIO

Display = Callable[[Sequence[str]], None]
"""Replace the live block with these lines; an empty sequence erases it."""

MAX_LISTED_CHECKS = 8
CURSOR_UP_AND_CLEAR = "\x1b[{count}A\x1b[J"


def hidden(lines: Sequence[str]) -> None:
    """The default display: none."""


def terminal_columns() -> int:
    return shutil.get_terminal_size(fallback=(80, 24)).columns


class LiveBlock:
    """Draws lines on `stream` and replaces them on the next call. A line is cut to the terminal's width, so one line is one row to move up."""

    def __init__(self, stream: TextIO, columns: Callable[[], int] = terminal_columns) -> None:
        self._stream = stream
        self._columns = columns
        self._enabled = stream.isatty() and os.environ.get("TERM") != "dumb"
        self._drawn = 0

    def show(self, lines: Sequence[str]) -> None:
        if not self._enabled:
            return
        width = max(self._columns() - 1, 1)
        if self._drawn:
            self._stream.write(CURSOR_UP_AND_CLEAR.format(count=self._drawn))
        self._stream.write("".join(f"{line[:width]}\n" for line in lines))
        self._stream.flush()
        self._drawn = len(lines)


def check_lines(label: str, required: Sequence[str], buckets: Mapping[str, set[str]]) -> list[str]:
    """The block for a CI wait: a count, then the required checks that have not passed, so a long list shrinks as the run goes on."""
    passed = {name for name in required if buckets.get(name) and buckets[name] <= {"pass", "skipping"}}
    rest = [name for name in required if name not in passed]
    lines = [f"{label}: {len(passed)}/{len(required)} required checks passed"]
    for name in rest[:MAX_LISTED_CHECKS]:
        state = "running" if buckets.get(name) else "not reported yet"
        lines.append(f"  {name}  ({state})")
    if len(rest) > MAX_LISTED_CHECKS:
        lines.append(f"  and {len(rest) - MAX_LISTED_CHECKS} more")
    return lines
