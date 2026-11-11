"""The certificate renewer unit restarts the apps named for it, after the app's own restart."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import jinja2
import pytest

TEMPLATE = Path(__file__).resolve().parents[4] / "ansible/roles/step_ca_cert/templates/cert-renewer@.service.j2"
ENV_TEMPLATE = Path(__file__).resolve().parents[4] / "ansible/roles/step_ca_cert/templates/cert-renewer.env.j2"


def post_commands() -> list[str]:
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined, autoescape=False)  # noqa: S701 - a unit file, not HTML
    text = env.from_string(TEMPLATE.read_text()).render(compose_deploy_dir="/opt/stacks")
    return re.findall(r"^ExecStartPost=(.*)$", text, re.MULTILINE)


def as_systemd_runs(line: str, variables: dict[str, str]) -> list[str]:
    """Expand the line as systemd does: %i and ${VAR} are substituted, and $$ becomes $."""
    expanded = line.replace("%i", "lldap")
    expanded = re.sub(r"\$\{(\w+)\}", lambda m: variables.get(m[1], ""), expanded)
    return ["/bin/sh", "-c", re.search(r"^/bin/sh -c '(.*)'$", expanded.replace("$$", "$"), re.DOTALL)[1]]


def run(tmp_path: Path, restarts_after: str, action: str = "restart") -> list[str]:
    fake = tmp_path / "docker"
    log = tmp_path / "calls"
    fake.write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    fake.chmod(0o755)
    line = next(c for c in post_commands() if "RENEW_RESTARTS_AFTER" in c)
    command = as_systemd_runs(line, {"RENEW_RESTARTS_AFTER": restarts_after, "RENEW_ACTION": action})
    command[2] = command[2].replace("/usr/bin/docker", str(fake))
    subprocess.run(command, check=True, env={"PATH": os.environ["PATH"]})
    return log.read_text().splitlines() if log.exists() else []


def test_each_named_app_is_restarted_in_its_own_compose_project(tmp_path: Path) -> None:
    assert run(tmp_path, "tinyauth other") == [
        "compose -f /opt/stacks/tinyauth/compose.yaml restart tinyauth",
        "compose -f /opt/stacks/other/compose.yaml restart other",
    ]


def test_nothing_is_restarted_when_no_app_is_named(tmp_path: Path) -> None:
    assert run(tmp_path, "") == []


def test_the_dependents_restart_after_the_apps_own_restart() -> None:
    commands = post_commands()
    own = next(i for i, c in enumerate(commands) if "RENEW_ACTION" in c)
    dependents = next(i for i, c in enumerate(commands) if "RENEW_RESTARTS_AFTER" in c)
    assert own < dependents


@pytest.mark.parametrize(("apps", "line"), [([], "RENEW_RESTARTS_AFTER="), (["tinyauth", "x"], "RENEW_RESTARTS_AFTER=tinyauth x")])
def test_the_env_file_lists_the_apps(apps: list[str], line: str) -> None:
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined, autoescape=False)  # noqa: S701 - an env file, not HTML
    text = env.from_string(ENV_TEMPLATE.read_text()).render(step_ca_cert_renew_restarts_after=apps)
    assert line in text.splitlines()
