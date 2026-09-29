"""Invariants of ADR 0065 that no single role's tests would notice breaking.

`compose_apps` is host intent and is never reassigned; every consumer reads
`resolved_apps`; only the definition in `group_vars/all/main.yaml` and its
Molecule stand-in read the catalog.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ANSIBLE_DIR = Path(__file__).resolve().parent.parent
MAIN_VARS = ANSIBLE_DIR / "inventory/group_vars/all/main.yaml"
HELPER = ANSIBLE_DIR / "roles/molecule_helpers/tasks/resolve_compose_apps.yaml"

# Code that runs a task or renders a template. Scenario data files are not here:
# they define `compose_apps` and the catalog, they don't consume the result.
CONSUMER_GLOBS = (
    "roles/*/tasks/**/*.yaml",
    "roles/*/handlers/**/*.yaml",
    "roles/*/defaults/**/*.yaml",
    "roles/*/templates/**/*.j2",
    "playbooks/*.yaml",
)
SCENARIO_GLOBS = ("roles/*/molecule/*/converge.yml", "roles/*/molecule/*/verify.yml", "roles/*/molecule/*/prepare.yml")

# A read of the variable in Jinja: piped, indexed or printed. `item.compose_apps`
# is a scenario's data for an `add_host` loop, not a read of a host's variable.
COMPOSE_APPS_READ = re.compile(r"(?<!item\.)(?<![\w.])compose_apps\s*(\||\[|\}\})|hostvars\[[^\]]+\]\.compose_apps|\bhv\.compose_apps")
# A scenario defines the catalog it supplies (`app_registry:`, or `... | from_yaml).app_registry` out of the real
# file) and passes it to the resolver; neither is a read of the resolved result.
CATALOG_READ = re.compile(r"(?<!\)\.)\bapp_registry\b(?!\.yaml|\s*:)")

# Play 1 of cleanup.yaml lists this host's intended app names to find orphaned stacks.
# The Molecule helper is the resolver's stand-in call site, so it reads the intent it resolves.
COMPOSE_APPS_READERS_ALLOWED = {"playbooks/cleanup.yaml", "roles/molecule_helpers/tasks/resolve_compose_apps.yaml"}
CATALOG_READERS_ALLOWED = {"roles/molecule_helpers/tasks/resolve_compose_apps.yaml"}


def _files(globs):
    return sorted({path for pattern in globs for path in ANSIBLE_DIR.glob(pattern) if path.is_file()})


def _rel(path: Path) -> str:
    return path.relative_to(ANSIBLE_DIR).as_posix()


def _code_lines(path: Path):
    """(line number, text) of every line that isn't a whole-line comment."""
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.lstrip().startswith("#"):
            yield number, line


def _walk(node):
    yield node
    children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
    for child in children:
        yield from _walk(child)


def _tasks_with(path: Path, module: str):
    """Every task in `path` calling `module`, short or fully-qualified."""
    for doc in yaml.safe_load_all(path.read_text()):
        for node in _walk(doc):
            if isinstance(node, dict):
                for key in (module, f"ansible.builtin.{module}"):
                    if key in node:
                        yield node, node[key]


def test_the_scan_finds_the_files_it_is_meant_to_guard():
    assert len(_files(CONSUMER_GLOBS)) > 50
    assert len(_files(SCENARIO_GLOBS)) > 50


def test_compose_apps_is_never_reassigned_by_a_task():
    offenders = []
    for path in [*_files(CONSUMER_GLOBS), *_files(SCENARIO_GLOBS), HELPER]:
        if path.suffix == ".j2":
            continue
        offenders += [_rel(path) for _, args in _tasks_with(path, "set_fact") if isinstance(args, dict) and "compose_apps" in args]
    assert offenders == []


def test_no_consumer_reads_compose_apps_as_a_resolved_definition():
    offenders = []
    for path in [*_files(CONSUMER_GLOBS), *_files(SCENARIO_GLOBS)]:
        if _rel(path) in COMPOSE_APPS_READERS_ALLOWED:
            continue
        offenders += [f"{_rel(path)}:{number}" for number, line in _code_lines(path) if COMPOSE_APPS_READ.search(line)]
    assert offenders == [], "read resolved_apps instead"


def test_only_the_resolver_call_sites_read_the_catalog():
    offenders = []
    for path in [*_files(CONSUMER_GLOBS), *_files(SCENARIO_GLOBS)]:
        if _rel(path) in CATALOG_READERS_ALLOWED:
            continue
        for number, line in _code_lines(path):
            if CATALOG_READ.search(line) and "resolve_apps(" not in line:
                offenders.append(f"{_rel(path)}:{number}")
    assert offenders == [], "read resolved_apps instead"


def test_the_molecule_stand_in_is_the_definition_in_group_vars():
    ((_, args),) = _tasks_with(HELPER, "set_fact")
    assert args["resolved_apps"] == yaml.safe_load(MAIN_VARS.read_text())["resolved_apps"]


@pytest.mark.parametrize("path", _files(SCENARIO_GLOBS), ids=_rel)
def test_a_scenario_host_built_with_add_host_carries_its_own_resolved_apps(path):
    for _, args in _tasks_with(path, "add_host"):
        if isinstance(args, dict) and "compose_apps" in args:
            assert "resolved_apps" in args, "hostvars[host].resolved_apps must resolve like production"
