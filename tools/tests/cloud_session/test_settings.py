"""The committed Claude Code settings: what they refuse, and that the hook they name runs the preparation module."""

from __future__ import annotations

import importlib.util
import json
import subprocess
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


def hook_commands() -> list[str]:
    return [hook["command"] for entry in SETTINGS["hooks"]["SessionStart"] for hook in entry["hooks"]]


def test_the_session_start_hook_names_a_module_that_exists() -> None:
    (command,) = hook_commands()

    assert importlib.util.find_spec(command.split(" -m ")[1].split(";")[0].strip()) is not None


def test_the_session_start_hook_runs_nothing_outside_a_cloud_session(tmp_path: Path) -> None:
    (command,) = hook_commands()

    # A project directory that does not exist: reaching it at all would fail.
    done = subprocess.run(["sh", "-c", command], env={"CLAUDE_PROJECT_DIR": str(tmp_path / "absent")}, capture_output=True, text=True, check=False)

    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
