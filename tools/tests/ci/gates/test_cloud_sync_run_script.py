"""cloud_sync's relay script bounds how long one stalled provider can hold a run, tighter than rclone's own defaults."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[4] / "ansible/roles/cloud_sync/templates/run.sh.j2"

# rclone's defaults for each bound, in seconds (retries are a count).
RCLONE_DEFAULTS = {"contimeout": 60, "timeout": 300, "low-level-retries": 10}
UNITS = {"s": 1, "m": 60, "h": 3600}


def copy_command() -> str:
    lines = [line for line in TEMPLATE.read_text().splitlines() if "rclone copy" in line and not line.lstrip().startswith("#")]
    assert len(lines) == 1, "run.sh.j2 no longer has exactly one rclone copy command"
    return lines[0]


def bound(flag: str) -> int:
    match = re.search(rf"--{flag}[ =](\d+)([smh]?)(?=\s)", copy_command())
    assert match, f"the rclone copy in run.sh.j2 sets no --{flag}"
    return int(match.group(1)) * UNITS.get(match.group(2), 1)


@pytest.mark.parametrize("flag", RCLONE_DEFAULTS, ids=RCLONE_DEFAULTS)
def test_the_copy_is_bounded_tighter_than_rclones_default(flag: str) -> None:
    assert 0 < bound(flag) < RCLONE_DEFAULTS[flag]
