"""Every task in the secrets role that calls ensure_vault_secret sets no_log: true.

The module returns the secret in plain text (a module cannot hide a value from
the task result and still hand it to the playbook), so the task's own no_log is
the only thing keeping the value out of -v/-vvv output.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

ROLE = Path(__file__).resolve().parents[1] / "roles/secrets"
MODULE = "ensure_vault_secret"


def calls_without_no_log(node, no_log: bool = False) -> Iterator[str]:
    """The name of every task under `node` that calls the module and does not have no_log: true.

    A block's no_log applies to the tasks inside it. Anything but the literal
    true counts as not set, so a templated value does not pass.
    """
    if isinstance(node, list):
        for item in node:
            yield from calls_without_no_log(item, no_log)
    elif isinstance(node, dict):
        no_log = node.get("no_log", no_log) is True
        if MODULE in node and not no_log:
            yield str(node.get("name", "(unnamed task)"))
        for value in node.values():
            yield from calls_without_no_log(value, no_log)


def calls(node) -> int:
    if isinstance(node, list):
        return sum(calls(item) for item in node)
    if isinstance(node, dict):
        return (MODULE in node) + sum(calls(value) for value in node.values())
    return 0


def _load(path: Path) -> list:
    return list(yaml.safe_load_all(path.read_text()))


ROLE_FILES = sorted(p for p in ROLE.rglob("*") if p.suffix in (".yml", ".yaml") and "files" not in p.relative_to(ROLE).parts)


class TestTheRoleCallsTheModuleOnlyWithNoLog:
    @pytest.mark.parametrize("path", ROLE_FILES, ids=lambda path: str(path.relative_to(ROLE)))
    def test_every_call_in_the_file_sets_no_log(self, path):
        assert list(calls_without_no_log(_load(path))) == []

    def test_the_role_calls_the_module_somewhere_so_the_check_is_not_vacuous(self):
        assert sum(calls(_load(path)) for path in ROLE_FILES) >= 2


class TestTheCheckItself:
    def test_a_task_with_no_log_true_passes(self):
        tasks = yaml.safe_load("- name: a\n  ensure_vault_secret: {}\n  no_log: true\n")

        assert list(calls_without_no_log(tasks)) == []

    @pytest.mark.parametrize(
        "no_log_line",
        [
            pytest.param("", id="absent"),
            pytest.param("  no_log: false\n", id="false"),
            pytest.param('  no_log: "{{ hide }}"\n', id="templated"),
        ],
    )
    def test_a_task_without_a_literal_true_is_reported_by_name(self, no_log_line):
        tasks = yaml.safe_load(f"- name: leaks\n  ensure_vault_secret: {{}}\n{no_log_line}")

        assert list(calls_without_no_log(tasks)) == ["leaks"]

    def test_a_block_with_no_log_covers_the_tasks_inside_it(self):
        tasks = yaml.safe_load("- block:\n    - name: inside\n      ensure_vault_secret: {}\n  no_log: true\n")

        assert list(calls_without_no_log(tasks)) == []

    def test_a_task_can_turn_off_what_its_block_set(self):
        tasks = yaml.safe_load("- block:\n    - name: inside\n      ensure_vault_secret: {}\n      no_log: false\n  no_log: true\n")

        assert list(calls_without_no_log(tasks)) == ["inside"]

    def test_a_task_that_does_not_call_the_module_is_ignored(self):
        tasks = yaml.safe_load("- name: other\n  ansible.builtin.debug:\n    msg: ensure_vault_secret\n")

        assert list(calls_without_no_log(tasks)) == []
