"""The committed Claude Code settings: no session link, and what they refuse."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SETTINGS = json.loads((REPO_ROOT / ".claude/settings.json").read_text())


def test_no_session_link_is_added_to_a_commit() -> None:
    assert SETTINGS["attribution"] == {"sessionUrl": False}


@pytest.mark.parametrize("rule", ["Agent", "Bash(git push *)", "Bash(gh *)"])
def test_the_tool_call_is_denied(rule: str) -> None:
    assert rule in SETTINGS["permissions"]["deny"]


def test_a_change_to_the_settings_runs_these_tests() -> None:
    filters = yaml.safe_load((REPO_ROOT / ".github/detect-changes-filters.yml").read_text())

    assert ".claude/**" in filters["python_unit_tests"]
