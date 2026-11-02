"""bootstrap-security.yaml changes nothing unless a stage is named, issues OpenBao's cert as deploy.yaml does, and publishes only on loopback until then."""

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


def play_6_openbao_cert_vars() -> dict:
    for play in load(ANSIBLE_DIR / "playbooks/deploy.yaml"):
        for task in play.get("tasks", []):
            if task.get("ansible.builtin.include_role", {}).get("name") == "step_ca_cert" and task["vars"]["step_ca_cert_app_name"] == "openbao":
                return task["vars"]
    raise AssertionError("deploy.yaml has no step_ca_cert include for openbao")


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


def test_stage_3_issues_with_the_variables_deploy_runs_for_openbao(bootstrap_tasks, openbao_image):
    stage_3 = next(task for task in bootstrap_tasks if task["tags"] == ["never", "stage3"])
    issue = next(task for task in stage_3["block"] if task.get("ansible.builtin.include_role", {}).get("name") == "step_ca_cert")
    assert issue["ansible.builtin.include_role"]["tasks_from"] == "issue.yaml"
    bootstrap_vars = {name: (openbao_image if value == "{{ openbao_image }}" else value) for name, value in issue["vars"].items()}
    assert bootstrap_vars == play_6_openbao_cert_vars()


def test_the_play_6_image_is_the_one_the_role_pins(openbao_image):
    # The placeholder is handed to the openbao user with this image.
    assert play_6_openbao_cert_vars()["step_ca_cert_chown_image"] == openbao_image
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
