"""What the maintainer reads before a replay runs code a series changes: a summary of the files on the stop list, and their diff.

Everything shown comes from patches nobody has read yet, so control and format characters are printed as escapes: a terminal would
otherwise act on them, and one could hide or reorder the lines under review. Colour is added after that, here.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from land_series.manifest import Layer


@dataclass(frozen=True)
class Change:
    """One file a commit changes, and how many lines of it."""

    path: str
    added: int
    removed: int


@dataclass(frozen=True)
class Stop:
    """A commit that changes files on the stop list: those files, and their diff."""

    layer: Layer
    changes: tuple[Change, ...]
    diff: str


# The first group with a matching prefix takes the file, so the tests come before the rest of `tools/`.
GROUPS = (
    ("hooks, configuration and dependencies", (".githooks/", ".pre-commit-config.yaml", ".config/", "pyproject.toml", "uv.lock")),
    ("CI workflows and actions", (".github/",)),
    ("tool tests", ("tools/tests/",)),
    ("tools code", ("tools/",)),
)
PROMPT = "Read the changes, then type 'yes' to replay, 'v' to view the diff (q returns here), anything else to stop: "
GREEN, RED, CYAN, BOLD, PLAIN = "\x1b[32m", "\x1b[31m", "\x1b[36m", "\x1b[1m", "\x1b[0m"


def visible(text: str) -> str:
    """`text` with every control, format and surrogate character but a tab and a newline written as an escape."""
    return "".join(
        char if char in "\t\n" or unicodedata.category(char) not in ("Cc", "Cf", "Cs") else char.encode("unicode_escape").decode("ascii") for char in text
    )


def summary(stops: Sequence[Stop]) -> list[str]:
    """The lines naming each commit on the stop list and its files, grouped by what runs them."""
    lines = ["These commits change code the replay and the checks run on this machine:"]
    for stop in stops:
        lines += ["", visible(f"{stop.layer.id}  {stop.layer.subject}")]
        grouped: dict[str, list[Change]] = {}
        for change in stop.changes:
            title = next(title for title, prefixes in GROUPS if change.path.startswith(prefixes))
            grouped.setdefault(title, []).append(change)
        for title, _ in GROUPS:
            if title in grouped:
                lines.append(f"  {title}")
                lines += [f"    +{change.added} -{change.removed}  {visible(change.path).replace(chr(10), '\\n')}" for change in grouped[title]]
    return lines


def _painted(diff: str) -> str:
    """The diff with added, removed and header lines coloured. `+++` and `---` are headers only before a file's first hunk."""
    painted = []
    in_hunk = False
    for line in diff.split("\n"):
        if line.startswith(("commit ", "diff --git ")):
            colour, in_hunk = BOLD, False
        elif line.startswith("@@"):
            colour, in_hunk = CYAN, True
        elif not in_hunk:
            colour = BOLD
        elif line.startswith("+"):
            colour = GREEN
        elif line.startswith("-"):
            colour = RED
        else:
            colour = ""
        painted.append(f"{colour}{line}{PLAIN}" if colour and line else line)
    return "\n".join(painted)


def page(stops: Sequence[Stop]) -> None:
    """Show the flagged files' diffs in `less`, which gives the terminal back as it was when it quits; print them when there is no pager."""
    text = "\n".join(f"commit {stop.layer.id}: {stop.layer.subject.replace(chr(10), ' ')}\n{stop.diff}" for stop in stops)
    text = visible(text)
    if os.environ.get("TERM") != "dumb":
        # `LESS` replaces the reader's own options, which may keep the pager's screen (`-X`) or quit on a short diff (`-F`).
        try:
            subprocess.run(["less"], input=_painted(text).encode(), env={**os.environ, "LESS": "R"}, check=False)
        except FileNotFoundError:
            pass
        else:
            return
    print(text, flush=True)


def ask(stops: Sequence[Stop]) -> bool:
    """Ask on the terminal, once for the whole series; with no terminal to ask on, refuse."""
    if not sys.stdin.isatty():
        return False
    print("\n".join(summary(stops)), end="\n\n")
    while True:
        try:
            answer = input(PROMPT).strip()
        except EOFError:
            return False
        if answer != "v":
            return answer == "yes"
        page(stops)
