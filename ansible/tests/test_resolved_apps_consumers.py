"""Invariants of ADR 0065 that no single role's tests would notice breaking.

`compose_apps` is host intent and is never reassigned; every consumer reads
`resolved_apps`; only the definition in `group_vars/all/main.yaml` and its
Molecule stand-in read the catalog. ADR 0068 adds the same stand-in rule for a
role that reads a `backup_plan`, its own host's or another's.

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
BACKUP_PLAN_HELPER = ANSIBLE_DIR / "roles/molecule_helpers/tasks/resolve_backup_plan.yaml"

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
# A scenario defines the catalog it supplies (`app_catalog:`, or `... | from_yaml).app_catalog` out of the real
# file) and passes it to the resolver; neither is a read of the resolved result.
CATALOG_READ = re.compile(r"(?<!\)\.)\bapp_catalog\b(?!\.yaml|\s*:)")

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


def _scenarios_using_the_stand_in():
    return [path for path in _files(SCENARIO_GLOBS) if path.name == "converge.yml" and "resolve_compose_apps.yaml" in path.read_text()]


@pytest.mark.parametrize("path", _scenarios_using_the_stand_in(), ids=_rel)
def test_a_scenario_using_the_stand_in_defines_its_own_catalog(path):
    # The stand-in passes `app_catalog` to the resolver as production does, where it is always defined.
    # A scenario with nothing to put in it says so with `app_catalog: {}`.
    scenario = path.parent
    sources = [path, *(p for p in scenario.rglob("*") if p.is_file() and {"host_vars", "group_vars"} & set(p.relative_to(scenario).parts))]
    assert any(re.search(r"^\s*app_catalog\s*:", source.read_text(), re.M) for source in sources)


# A role that reads a `backup_plan` runs, in Molecule, where there is no `group_vars/all`. A scenario host
# built with `add_host` carries the plan the definition would give it, a scenario that resolves its own
# apps works out its own plan with the same expression, and the scenario defines the `backup_defaults`
# that computes it (ADR 0068).
BACKUP_PLAN_READ = re.compile(r"\bbackup_plan\b")


def _backup_plan_reader_roles() -> set[str]:
    roles_dir = ANSIBLE_DIR / "roles"
    readers = {
        path.relative_to(roles_dir).parts[0]
        for path in _files(CONSUMER_GLOBS)
        if path.is_relative_to(roles_dir) and any(BACKUP_PLAN_READ.search(line) for _, line in _code_lines(path))
    }
    return readers - {"molecule_helpers"}


def _reader_scenario_files():
    readers = _backup_plan_reader_roles()
    return [path for path in _files(SCENARIO_GLOBS) if path.relative_to(ANSIBLE_DIR / "roles").parts[0] in readers]


def test_the_scan_finds_the_roles_that_read_backup_plan():
    assert {"backup_agent", "cloud_sync", "restore_discovery"} <= _backup_plan_reader_roles()


def test_the_backup_plan_stand_in_is_the_definition_in_group_vars():
    ((_, args),) = _tasks_with(BACKUP_PLAN_HELPER, "set_fact")
    assert args["backup_plan"] == yaml.safe_load(MAIN_VARS.read_text())["backup_plan"]


@pytest.mark.parametrize("path", [p for p in _reader_scenario_files() if p.name == "converge.yml" and "resolve_compose_apps.yaml" in p.read_text()], ids=_rel)
def test_a_reader_scenario_that_resolves_its_apps_works_out_its_plan_too(path):
    assert "resolve_backup_plan.yaml" in path.read_text()


@pytest.mark.parametrize("path", _reader_scenario_files(), ids=_rel)
def test_a_reader_scenario_host_carries_the_plan_its_apps_would_give_it(path):
    for _, args in _tasks_with(path, "add_host"):
        if isinstance(args, dict) and "compose_apps" in args:
            assert "backup_plan" in args, "hostvars[host].backup_plan must resolve like production"
            assert "resolve_apps(app_catalog)" in args["backup_plan"]
            assert "| backup_plan(backup_defaults)" in args["backup_plan"]


@pytest.mark.parametrize("path", [p for p in _reader_scenario_files() if p.name == "converge.yml" and "backup_plan" in p.read_text()], ids=_rel)
def test_a_reader_scenario_defines_every_backup_default(path):
    wanted = set(yaml.safe_load(MAIN_VARS.read_text())["backup_defaults"])
    defined = [play["vars"]["backup_defaults"] for doc in yaml.safe_load_all(path.read_text()) for play in doc if "backup_defaults" in (play.get("vars") or {})]
    assert defined, "define backup_defaults in the play's vars"
    assert all(set(d) == wanted for d in defined)


# The catalog was called `app_registry` until ADR 0065. Accepted decision revisions and the project
# records keep the old name as history; nothing else names it.
OLD_NAME = re.compile("app_" + "registry|app " + "registry", re.I)
HISTORICAL = ("docs/decisions/", "docs/projects/", "docs/project-planning.md")
SKIPPED_DIRS = {".git", ".venv", ".ansible", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}


def test_nothing_still_uses_the_old_catalog_name():
    root = ANSIBLE_DIR.parent
    offenders = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if not path.is_file() or SKIPPED_DIRS & set(path.relative_to(root).parts) or relative.startswith(HISTORICAL) or path == Path(__file__):
            continue
        if path.name == "uv.lock" or path.suffix in {".pyc", ".png", ".jpg", ".gz", ".zip"}:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        offenders += [f"{relative}:{number}" for number, line in enumerate(text.splitlines(), 1) if OLD_NAME.search(line)]
    assert offenders == []


def _yaml_files():
    for path in sorted(ANSIBLE_DIR.rglob("*.y*ml")):
        if path.suffix in {".yaml", ".yml"} and not path.is_symlink() and ".ansible" not in path.relative_to(ANSIBLE_DIR).parts:
            yield path


def _is_route_map(value) -> bool:
    return isinstance(value, dict) and bool(value) and all(isinstance(route, dict) for route in value.values())


def test_no_app_entry_still_declares_its_routes_under_the_old_key():
    """`caddy:` is now `routes:`. The old key is ignored without an error, so an app that keeps it loses its route and DNS record."""
    offenders = []
    for path in _yaml_files():
        for doc in yaml.safe_load_all(path.read_text()):
            offenders += [_rel(path) for node in _walk(doc) if isinstance(node, dict) and _is_route_map(node.get("caddy"))]
    assert offenders == []
