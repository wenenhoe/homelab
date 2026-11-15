"""The record of how long each Molecule scenario took, and the tree it was measured on.

One JSON file holds it, `{"version": 1, "roles": {role: entry}}`, where an
entry is `{"fingerprint": ..., "measured": "YYYY-MM-DD", "seconds": {scenario: n}}`.
A file that is missing, unreadable or of another version reads as empty, so
the run measures every role again instead of trusting numbers it cannot read.
"""

from __future__ import annotations

import json
from pathlib import Path

VERSION = 1
RESULT_FIELDS = 4


class ResultError(Exception):
    """A results file that `molecule-test-all.sh` could not have written."""


def empty() -> dict:
    return {"version": VERSION, "roles": {}}


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except OSError, ValueError:
        return empty()
    if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("roles"), dict):
        return empty()
    return data


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def parse_results(text: str, source: str = "results") -> list[tuple[str, str, int, str]]:
    """`role<TAB>scenario<TAB>seconds<TAB>result` rows, as `molecule-test-all.sh` writes them."""
    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != RESULT_FIELDS or not fields[2].isdigit():
            raise ResultError(f"{source}:{number}: expected role, scenario, seconds and result separated by tabs, got {line!r}")
        rows.append((fields[0], fields[1], int(fields[2]), fields[3]))
    return rows
