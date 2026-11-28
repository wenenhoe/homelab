"""No two Molecule scenarios may start a throwaway helper under one name.

`molecule-test-all.sh -j N` runs scenarios side by side on one Docker daemon.
Two scenarios whose helpers (the `molecule_helpers` `start_*_test_target.yaml`
tasks) land on that daemon and share a container, network, host directory or
published port remove or reuse each other's helper.

A helper started inside a scenario's own Docker-in-Docker platform lives on
that platform's daemon, so it cannot collide and is not counted. Only a helper
started on the control node is: a play on `localhost`, or a task under a
`delegate_to: localhost`.
"""

from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, NamedTuple

import jinja2
import pytest
import yaml

ROLES_DIR = Path(__file__).resolve().parent.parent / "roles"
HELPER_NAMES = Path("molecule_helpers") / "vars" / "helper_names.yml"
PREFIX = "molecule_helpers_"
CONTROL_NODE = "localhost"

# Per helper: the variable (without PREFIX) that sets each resource and the
# value the helper uses when none is set. A resource with no variable is a
# literal in the helper, so every scenario that starts the helper shares it.
HELPERS: dict[str, dict[str, tuple[str, str | int | None, str | None]]] = {
    # resource key: (kind, default, variable or None)
    "start_step_ca_test_target.yaml": {
        "step_ca_container_name": ("container", "step-ca-test", "step_ca_container_name"),
        "step_ca_network_name": ("network", None, "step_ca_network_name"),
    },
    "start_openbao_test_target.yaml": {
        "openbao_container_name": ("container", "openbao-test", "openbao_container_name"),
        "openbao_network_name": ("network", None, "openbao_network_name"),
        "openbao_host_port": ("port", 18200, "openbao_host_port"),
        "openbao_cert_dir": ("directory", "/tmp/molecule-openbao-test-certs", "openbao_cert_dir"),
        "openbao_data_dir": ("directory", "/tmp/molecule-openbao-test-data", "openbao_data_dir"),
    },
    "start_lldap_test_target.yaml": {
        "lldap_container": ("container", "lldap-test", None),
        "lldap_network_name": ("network", None, "lldap_network_name"),
        "lldap_certs": ("directory", "/tmp/lldap-test-certs", None),
    },
    "start_seaweedfs_test_target.yaml": {
        "seaweedfs_container": ("container", "seaweedfs-test", None),
        "seaweedfs_network_name": ("network", None, "seaweedfs_network_name"),
        "seaweedfs_identity": ("directory", "/tmp/seaweedfs-test-s3-identity.json", None),
    },
}

Use = tuple[str, str, str]  # (scenario, helper, resource key)


class Resource(NamedTuple):
    kind: str
    value: str


def _render(value: Any, context: dict[str, Any]) -> Any:
    """Render a Jinja string against `context`, repeatedly, until it is plain."""
    # Names and paths, not HTML: escaping would change them.
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)  # noqa: S701
    env.filters["basename"] = lambda path: Path(path).name
    for _ in range(10):
        if not isinstance(value, str) or "{{" not in value:
            return value
        value = env.from_string(value).render(context)
    raise AssertionError(f"template does not settle: {value!r}")


def _scenario_context(role: str, scenario: str, play_vars: dict[str, Any]) -> dict[str, Any]:
    """The variables a scenario's helper calls can read, as Molecule sets them."""
    env = {
        "MOLECULE_PROJECT_DIRECTORY": str(ROLES_DIR / role),
        "MOLECULE_SCENARIO_NAME": scenario,
    }
    return {**play_vars, "lookup": lambda kind, key: env[key] if kind == "env" else ""}


def _walk_tasks(tasks: list[dict[str, Any]], delegated: bool):
    """Yield (task, runs_on_control_node) for every task, blocks included."""
    for task in tasks or []:
        here = delegated or task.get("delegate_to") == CONTROL_NODE
        yield task, here
        for key in ("block", "rescue", "always"):
            yield from _walk_tasks(task.get(key), here)


def _starts(playbook: Path) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Helper starts on the control node: (helper file, include vars, play vars)."""
    found = []
    for play in yaml.safe_load(playbook.read_text()) or []:
        play_vars = dict(play.get("vars") or {})
        for vars_file in play.get("vars_files") or []:
            if str(vars_file).endswith(str(HELPER_NAMES)):
                helper_names = ROLES_DIR / HELPER_NAMES
                play_vars = {**yaml.safe_load(helper_names.read_text()), **play_vars}
        on_control = play.get("hosts") == CONTROL_NODE
        for section in ("pre_tasks", "tasks", "post_tasks"):
            for task, delegated in _walk_tasks(play.get(section), on_control):
                include = task.get("ansible.builtin.include_role") or task.get("include_role")
                if not delegated or not include or include.get("name") != "molecule_helpers":
                    continue
                helper = include.get("tasks_from")
                if helper in HELPERS:
                    found.append((helper, dict(task.get("vars") or {}), play_vars))
    return found


def uses(roles_dir: Path = ROLES_DIR) -> dict[Resource, set[tuple[str, str]]]:
    """Each resource on the control node's daemon, and the (scenario, helper) using it."""
    users: dict[Resource, set[tuple[str, str]]] = defaultdict(set)
    for converge in sorted(roles_dir.glob("*/molecule/*/*.yml")):
        if converge.name == "molecule.yml":
            continue
        scenario_dir = converge.parent
        role, scenario = scenario_dir.parent.parent.name, scenario_dir.name
        for helper, include_vars, play_vars in _starts(converge):
            context = _scenario_context(role, scenario, {**play_vars, **include_vars})
            for kind, default, variable in HELPERS[helper].values():
                value = context.get(PREFIX + variable) if variable else None
                value = default if value is None else _render(value, context)
                if value is not None:
                    users[Resource(kind, str(value))].add((f"{role}/{scenario}", helper))
    return users


def collisions(roles_dir: Path = ROLES_DIR) -> list[str]:
    """One line per resource that two scenarios would both use at once."""
    lines = []
    for resource, who in sorted(uses(roles_dir).items()):
        scenarios = sorted({scenario for scenario, _ in who})
        if len(scenarios) > 1:
            lines.append(f"{resource.kind} {resource.value}: {', '.join(scenarios)}")
    return lines


def test_no_two_scenarios_share_a_helper_resource():
    assert collisions() == []


def test_the_secrets_scenarios_are_what_the_check_counts():
    """A check that counts nothing passes for any tree, so it must see them."""
    scenarios = {s for who in uses().values() for s, _ in who}
    assert scenarios == {
        "secrets/rotate_secret",
        "secrets/snapshot_restore",
        "secrets/vault_backed",
        "secrets/vault_manual_missing",
    }


def test_the_four_secrets_scenarios_each_hold_their_own_resources():
    by_kind = defaultdict(set)
    for resource in uses():
        by_kind[resource.kind].add(resource.value)
    assert {k: len(v) for k, v in by_kind.items()} == {
        "container": 8,
        "network": 4,
        "port": 4,
        "directory": 8,
    }


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A copy of the roles' scenarios, with the helper names the real tree has."""
    for source in ROLES_DIR.glob("*/molecule/*/*.yml"):
        target = tmp_path / "roles" / source.relative_to(ROLES_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, target)
    return tmp_path / "roles"


@pytest.mark.parametrize(
    ("old", "new", "shared"),
    [
        pytest.param(
            "secrets-rotate-secret-net",
            "secrets-vault-backed-net",
            "network secrets-vault-backed-net: secrets/rotate_secret, secrets/vault_backed",
            id="network",
        ),
        pytest.param(
            "secrets_rotate_secret_test_openbao_port: 18201",
            "secrets_rotate_secret_test_openbao_port: 18200",
            "port 18200: secrets/rotate_secret, secrets/vault_backed",
            id="port",
        ),
    ],
)
def test_the_check_fails_when_a_scenario_shares_a_name(tree: Path, old: str, new: str, shared: str):
    converge = tree / "secrets" / "molecule" / "rotate_secret" / "converge.yml"
    converge.write_text(converge.read_text().replace(old, new))
    assert shared in collisions(tree)


def test_the_check_fails_when_a_scenario_names_its_helpers_by_a_literal(tree: Path):
    converge = tree / "secrets" / "molecule" / "vault_backed" / "converge.yml"
    converge.write_text(
        converge.read_text().replace(
            "molecule_helpers_openbao_network_name: secrets-vault-backed-net",
            "molecule_helpers_openbao_container_name: openbao-test\n            molecule_helpers_openbao_network_name: secrets-vault-backed-net",
        )
    )
    other = tree / "secrets" / "molecule" / "rotate_secret" / "converge.yml"
    other.write_text(
        other.read_text().replace(
            "molecule_helpers_openbao_network_name: secrets-rotate-secret-net",
            "molecule_helpers_openbao_container_name: openbao-test\n            molecule_helpers_openbao_network_name: secrets-rotate-secret-net",
        )
    )
    assert "container openbao-test: secrets/rotate_secret, secrets/vault_backed" in collisions(tree)


def test_a_helper_inside_a_scenarios_own_platform_is_not_counted(tree: Path):
    """Two scenarios may use `step-ca-test`: each has its own daemon."""
    tree_uses = uses(tree)
    assert not any(scenario.startswith("step_ca_cert/") for who in tree_uses.values() for scenario, _ in who)
