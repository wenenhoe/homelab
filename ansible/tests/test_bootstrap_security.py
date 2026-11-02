"""bootstrap-security.yaml changes nothing unless a stage is named, shares OpenBao's cert tasks with deploy.yaml, and publishes only on loopback until then."""

from __future__ import annotations

from pathlib import Path

import jinja2
import pytest
import yaml

ANSIBLE_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = ANSIBLE_DIR.parent
STAGE_TAGS = {"stage1", "stage2", "stage3"}


def load(path: Path):
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def bootstrap_tasks() -> list[dict]:
    (play,) = load(ANSIBLE_DIR / "playbooks/bootstrap-security.yaml")
    return play["tasks"]


@pytest.fixture(scope="module")
def openbao_image() -> str:
    return load(ANSIBLE_DIR / "roles/openbao/defaults/main.yaml")["openbao_image"]


def render_openbao_compose(**variables: str) -> dict:
    template = (REPO_DIR / "docker/openbao/compose.yaml.j2").read_text()
    return yaml.safe_load(jinja2.Template(template).render(server_timezone="UTC", **variables))


def openbao_role_includes(tasks: list[dict]) -> dict[str, dict]:
    """The `openbao` role includes among tasks (recursing into blocks), keyed by the task file they run."""
    found: dict[str, dict] = {}
    for task in tasks:
        include = task.get("ansible.builtin.include_role", {})
        if include.get("name") == "openbao":
            found[include.get("tasks_from", "main.yaml")] = task
        found.update(openbao_role_includes(task.get("block", [])))
    return found


def step_ca_cert_vars(tasks: list[dict]) -> list[dict]:
    """Every `step_ca_cert_*` variable set on a task that includes the step_ca_cert role."""
    return [
        {name: value for name, value in task.get("vars", {}).items() if name.startswith("step_ca_cert_")}
        for task in tasks
        if task.get("ansible.builtin.include_role", {}).get("name") == "step_ca_cert" and task.get("vars")
    ]


def all_tasks(tasks: list[dict]) -> list[dict]:
    flat = []
    for task in tasks:
        flat.append(task)
        flat.extend(all_tasks(task.get("block", [])))
    return flat


def test_every_top_level_block_carries_never_and_one_stage(bootstrap_tasks):
    # A run that names no tag must not touch the host.
    for task in bootstrap_tasks:
        tags = set(task["tags"])
        assert "never" in tags, task["name"]
        assert tags & STAGE_TAGS, task["name"]


def test_the_stages_the_header_names_exist(bootstrap_tasks):
    assert set().union(*(set(task["tags"]) for task in bootstrap_tasks)) == STAGE_TAGS | {"never"}


def test_only_stage_1_publishes_openbao_on_loopback(bootstrap_tasks):
    published = {task["name"]: task.get("vars", {}).get("openbao_publish_address") for task in bootstrap_tasks}
    assert [name for name, address in published.items() if address] == ["Stage 1 - OpenBao on a placeholder cert"]
    assert published["Stage 1 - OpenBao on a placeholder cert"] == "127.0.0.1"


@pytest.mark.parametrize(
    ("variables", "published"),
    [
        pytest.param({}, "0.0.0.0:8200:8200", id="default-is-the-lan"),
        pytest.param({"openbao_publish_address": "127.0.0.1"}, "127.0.0.1:8200:8200", id="bootstrap-is-loopback"),
    ],
)
def test_the_compose_file_publishes_on_the_address_it_is_given(variables, published):
    assert render_openbao_compose(**variables)["services"]["openbao"]["ports"] == [published]


def test_stage_3_issues_through_the_tasks_deploy_runs(bootstrap_tasks):
    stage_3 = next(task for task in bootstrap_tasks if task["tags"] == ["never", "stage3"])
    issue = openbao_role_includes(stage_3["block"])["cert.yaml"]
    assert issue["vars"] == {"openbao_cert_tasks_from": "issue.yaml"}


def test_deploy_runs_the_whole_step_ca_cert_role_for_openbao():
    (play_6,) = [play for play in load(ANSIBLE_DIR / "playbooks/deploy.yaml") if play["name"] == "Wire lldap, tinyauth, and openbao into step-ca"]
    assert "vars" not in openbao_role_includes(play_6["tasks"])["cert.yaml"]


def test_neither_playbook_spells_openbao_cert_variables(bootstrap_tasks):
    # They have one home, roles/openbao/tasks/cert.yaml.
    deploy_tasks = [task for play in load(ANSIBLE_DIR / "playbooks/deploy.yaml") for task in play.get("tasks", [])]
    spelled = [
        variables
        for variables in step_ca_cert_vars(all_tasks(bootstrap_tasks) + all_tasks(deploy_tasks))
        if variables.get("step_ca_cert_app_name") == "openbao"
    ]
    assert spelled == []


def test_the_cert_tasks_pass_the_image_the_role_pins(openbao_image):
    # The chown image resolves the openbao user, so it has to be the running image.
    (include,) = load(ANSIBLE_DIR / "roles/openbao/tasks/cert.yaml")
    assert include["vars"]["step_ca_cert_chown_image"] == "{{ openbao_image }}"
    assert render_openbao_compose()["services"]["openbao"]["image"] == openbao_image


def test_the_pre_deploy_play_reads_no_secret():
    # bootstrap-security.yaml runs it before OpenBao exists on the host.
    files = [
        ANSIBLE_DIR / "playbooks/predeploy.yaml",
        *(ANSIBLE_DIR / "roles/docker").rglob("*.yaml"),
        *(ANSIBLE_DIR / "roles/qemu_guest_agent").rglob("*.yaml"),
        ANSIBLE_DIR / "roles/compose/tasks/preinit.yaml",
    ]
    # Parsed, so a comment that names the variable is not a read of it.
    reading = [str(path.relative_to(ANSIBLE_DIR)) for path in files if "molecule" not in path.parts and "secrets_generated" in str(load(path))]
    assert reading == []
