"""The cloud session's preparation: what it changes on the session's machine, and that it does nothing elsewhere."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from cloud_session import prepare

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def machine(tmp_path: Path) -> prepare.Machine:
    (tmp_path / "bundle.crt").write_text("bundle\n")
    (tmp_path / "hosts").write_text("127.0.0.1 localhost\n")
    (tmp_path / "cgroup").mkdir()
    return prepare.Machine(
        ca_bundle=tmp_path / "bundle.crt",
        daemon_json=tmp_path / "docker/daemon.json",
        wrapper=tmp_path / "runc-ca",
        hosts=tmp_path / "hosts",
        cgroup=tmp_path / "cgroup",
        pid_file=tmp_path / "docker.pid",
        processes=tmp_path / "proc",
        log=tmp_path / "dockerd.log",
    )


@pytest.mark.parametrize("remote", [pytest.param({}, id="unset"), pytest.param({"CLAUDE_CODE_REMOTE": "false"}, id="false")])
def test_outside_a_cloud_session_nothing_is_touched(machine: prepare.Machine, remote: dict[str, str], capsys: pytest.CaptureFixture[str]) -> None:
    before = machine.hosts.read_text()

    assert prepare.main(remote, machine) == 0

    assert (machine.hosts.read_text(), machine.wrapper.exists(), capsys.readouterr().out) == (before, False, "")


def test_the_daemon_config_names_the_mirror_and_leaves_one_that_exists(machine: prepare.Machine) -> None:
    prepare.write_daemon_config(machine)
    assert json.loads(machine.daemon_json.read_text()) == {"registry-mirrors": ["https://mirror.gcr.io"]}

    machine.daemon_json.write_text("{}")
    prepare.write_daemon_config(machine)
    assert machine.daemon_json.read_text() == "{}"


def test_the_wrapper_is_installed_only_where_there_is_a_bundle_to_read(machine: prepare.Machine) -> None:
    assert prepare.install_wrapper(machine) is True
    assert machine.wrapper.read_text() == prepare.WRAPPER_SOURCE.read_text()
    assert machine.wrapper.stat().st_mode & 0o777 == 0o755

    machine.wrapper.unlink()
    machine.ca_bundle.unlink()
    assert prepare.install_wrapper(machine) is False
    assert not machine.wrapper.exists()


def test_every_scenario_name_in_the_tree_is_added_once(machine: prepare.Machine) -> None:
    names = prepare.scenario_names(REPO_ROOT)

    prepare.add_hosts(machine, names)
    prepare.add_hosts(machine, names)

    assert {"vault-backed.localtest.me", "openbao.vault-backed.localtest.me"} <= set(names)
    assert machine.hosts.read_text() == f"127.0.0.1 localhost\n127.0.0.1 {' '.join(names)}\n"


@pytest.mark.parametrize("before", [pytest.param({}, id="no proxy exceptions"), pytest.param({"NO_PROXY": "a.example"}, id="some already")])
def test_the_test_domain_is_added_to_the_proxy_exceptions_of_later_commands(tmp_path: Path, before: dict[str, str]) -> None:
    env_file = tmp_path / "env"
    prepare.bypass_proxy(str(env_file))
    prepare.bypass_proxy(str(env_file))

    shown = subprocess.run(["bash", "-c", f'. {env_file}; echo "$NO_PROXY"'], env=before, capture_output=True, text=True, check=True).stdout

    assert shown.strip() == ",".join([*before.values(), ".localtest.me"])
    assert len(env_file.read_text().splitlines()) == 2


@pytest.mark.parametrize(
    ("controllers", "wrapped", "starts"),
    [
        pytest.param(False, True, ["unshare", "dockerd", "--default-runtime"], id="cgroup v1, wrapped"),
        pytest.param(True, True, ["dockerd", "--default-runtime"], id="cgroup v2, wrapped"),
        pytest.param(True, False, ["dockerd"], id="cgroup v2, no bundle"),
    ],
)
def test_the_daemon_gets_cgroup2_and_the_wrapper_only_where_needed(machine: prepare.Machine, controllers: bool, wrapped: bool, starts: list[str]) -> None:
    if controllers:
        (machine.cgroup / "cgroup.controllers").write_text("cpu\n")

    command = prepare.daemon_command(machine, wrapped)

    assert [word for word in command if word in {"unshare", "dockerd", "--default-runtime"}] == starts
    assert command[0] == starts[0]


@pytest.mark.parametrize(("owner", "kept"), [pytest.param("dockerd", True, id="a running daemon"), pytest.param("bash", False, id="another process")])
def test_a_pid_file_that_names_no_daemon_is_removed(machine: prepare.Machine, owner: str, kept: bool) -> None:
    machine.pid_file.write_text("41\n")
    (machine.processes / "41").mkdir(parents=True)
    (machine.processes / "41/comm").write_text(f"{owner}\n")

    prepare.clear_stale_pid_file(machine)

    assert machine.pid_file.exists() is kept


def test_a_daemon_already_running_with_the_wrapper_is_left_running(machine: prepare.Machine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prepare, "docker_info", create_autospec(prepare.docker_info, return_value="ca"))

    assert prepare.start_docker(machine, True) == "dockerd was already running"
    assert not machine.log.exists()


def test_a_daemon_running_without_the_wrapper_is_reported(machine: prepare.Machine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prepare, "docker_info", create_autospec(prepare.docker_info, return_value="runc"))

    with pytest.raises(RuntimeError, match="without the certificate wrapper"):
        prepare.start_docker(machine, True)


def test_a_failed_step_is_reported_and_the_others_still_run(
    machine: prepare.Machine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(prepare, "start_docker", create_autospec(prepare.start_docker, side_effect=RuntimeError("no daemon")))
    machine.hosts.unlink()

    assert prepare.main({"CLAUDE_CODE_REMOTE": "true"}, machine) == 0

    out = capsys.readouterr().out
    assert "FAILED to add the scenario names" in out
    assert "FAILED to start dockerd: no daemon" in out
    assert machine.daemon_json.exists()


def test_it_imports_only_the_standard_library() -> None:
    tree = ast.parse(Path(prepare.__file__).read_text(), feature_version=(3, 12))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert {name.split(".")[0] for name in imported} <= sys.stdlib_module_names
