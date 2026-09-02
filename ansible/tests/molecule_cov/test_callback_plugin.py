"""Unit tests for callback_plugins/molecule_coverage.py's static helpers.

Scoped deliberately to _json_safe_item and _role_from_molecule_env - the
two pieces of real logic that don't need a live Ansible task-execution
run to exercise, since both are @staticmethod and called directly rather
than through the instance. The v2_runner_on_*/_write_event side (writing
JSONL from real Ansible Result objects) needs a live `molecule test` run
to observe honestly - see the PR description for why that's out of scope
here rather than mocked.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import sys
from pathlib import Path

CALLBACK_PLUGINS_DIR = Path(__file__).resolve().parent.parent.parent / "molecule-coverage" / "callback_plugins"
sys.path.insert(0, str(CALLBACK_PLUGINS_DIR))

import molecule_coverage as callback_mod  # noqa: E402

CallbackModule = callback_mod.CallbackModule


def test_json_safe_item_passes_through_serializable_values():
    assert CallbackModule._json_safe_item("a string") == "a string"
    assert CallbackModule._json_safe_item(42) == 42
    assert CallbackModule._json_safe_item({"key": [1, 2, 3]}) == {"key": [1, 2, 3]}
    assert CallbackModule._json_safe_item(None) is None


def test_json_safe_item_falls_back_to_str_for_non_serializable_values():
    class Unserializable:
        def __str__(self):
            return "<custom repr>"

    assert CallbackModule._json_safe_item(Unserializable()) == "<custom repr>"


def test_role_from_molecule_env_uses_the_project_directory_basename(monkeypatch):
    monkeypatch.setenv("MOLECULE_PROJECT_DIRECTORY", "/home/user/repo/ansible/roles/caddy")
    assert CallbackModule._role_from_molecule_env() == "caddy"


def test_role_from_molecule_env_none_when_unset(monkeypatch):
    monkeypatch.delenv("MOLECULE_PROJECT_DIRECTORY", raising=False)
    assert CallbackModule._role_from_molecule_env() is None
