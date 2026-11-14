from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from conftest import RecordingRunner
from scratch_run import node as node_module
from scratch_run.node import REMOTE_DIR, NodeBackend, run_command
from scratch_run.spec import Spec

REAL_WHICH = shutil.which
URL = "https://mirror.example/opnsense/OPNsense-26.1-nano-amd64.img.bz2"
SUM = "a" * 64
ENV = {
    "NODE": "root@pve",
    "PROXMOX_ENDPOINT": "https://pve:8006",
    "PROXMOX_API_TOKEN": "u@pam!id=tok-secret-value",
    "HTTPS_PROXY": "http://proxy",
    "PATH": "/usr/bin",
}


@pytest.fixture
def out(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("scratch-out")


@pytest.fixture
def runner() -> RecordingRunner:
    # On a node with nothing left over: `qm status` and `test -e` exit non-zero when the VM and the directory are not there.
    return RecordingRunner(rules={"qm status": (1, "no such VM"), "test -e": (1, "")})


def backend(out, runner, env=ENV, resolver=lambda name: "127.0.0.1") -> NodeBackend:
    made = NodeBackend(out, URL, SUM, env, runner=runner, resolver=resolver)
    runner.rules = {"collection list": (0, f'"{made.release()}"')} | runner.rules  # the pinned release is installed
    return made


@pytest.fixture(autouse=True)
def every_tool_is_installed(monkeypatch):
    monkeypatch.setattr(node_module.shutil, "which", create_autospec(REAL_WHICH, return_value="/usr/bin/tool"))


def test_a_run_that_can_start_has_no_problem(out, runner, rehearsal):
    assert backend(out, runner).preflight(rehearsal) == []


def test_every_missing_precondition_is_named_in_one_pass(out, runner, rehearsal, monkeypatch):
    monkeypatch.setattr(node_module.shutil, "which", create_autospec(REAL_WHICH, return_value=None))
    made = NodeBackend(out, "http://bad/url", "XYZ", {}, runner=runner, resolver=lambda name: None)
    problems = " | ".join(made.preflight(rehearsal))
    for part in (
        "NODE is not set",
        "PROXMOX_ENDPOINT is not set",
        "PROXMOX_API_TOKEN is not set",
        "image URL must be an https",
        "image checksum must be 64",
        "ssh is not installed",
        "must resolve to 127.0.0.1",
    ):
        assert part in problems
    assert runner.calls == []


def test_an_out_dir_inside_the_repository_is_refused(rehearsal, runner):
    made = NodeBackend(node_module.REPO / "scratch-out", URL, SUM, ENV, runner=runner, resolver=lambda name: "127.0.0.1")
    assert any("must be outside the repository" in problem for problem in made.preflight(rehearsal))


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        pytest.param({"ssh": (255, "denied")}, "cannot ssh to root@pve without a prompt", id="no-ssh"),
        pytest.param({"qm status": (0, "status: stopped")}, "VM 501 exists on the node", id="old-vm"),
        pytest.param({"test -e": (0, "")}, f"{REMOTE_DIR} exists on the node", id="old-canaries"),
        pytest.param({"collection list": (0, "[]")}, "oxlorg.opnsense .* is not installed", id="no-collection"),
    ],
)
def test_the_node_and_the_collection_are_checked(out, runner, rehearsal, rule, message):
    made = backend(out, runner)
    runner.rules = runner.rules | rule
    assert any(re.search(message, problem) for problem in made.preflight(rehearsal))


def test_a_spec_that_sets_vlans_needs_a_scratch_script_that_takes_them(out, runner, rehearsal, tmp_path, monkeypatch):
    spec = Spec(rehearsal.name, rehearsal.description, (20, 70), {}, None, rehearsal.steps[:1])
    script = tmp_path / "scratch_gateway.sh"
    script.write_text("#!/bin/sh\n")
    made = backend(out, runner)
    made.gateway_script = script
    assert any("does not take SEED_VLANS" in problem for problem in made.preflight(spec))
    script.write_text("# SEED_VLANS\n")
    assert not any("SEED_VLANS" in problem for problem in made.preflight(spec))


def test_up_passes_the_seed_vlans_and_the_pinned_release_and_writes_the_plays_variables(out, runner, rehearsal):
    made = backend(out, runner)
    (out / "first-boot").mkdir()
    made.cert.write_text("cert")
    spec = Spec(rehearsal.name, rehearsal.description, (20, 70), rehearsal.play_vars, rehearsal.block_rule, rehearsal.steps)
    assert made.up(spec)[0] == 0
    argv, env, _ = runner.calls[0]
    assert argv[1:] == ["up", str(out), URL, SUM]
    assert (env["SEED_VLANS"], env["WANT_VERSION"]) == ("20,70", made.release())
    assert json.loads((out / "extra-vars.json").read_text()) == rehearsal.play_vars


def test_up_without_vlans_leaves_the_seeds_own_list(out, runner, rehearsal):
    made = backend(out, runner)
    made.up(rehearsal)
    assert "SEED_VLANS" not in runner.calls[0][1]


def test_up_that_leaves_no_certificate_fails(out, runner, rehearsal):
    status, output = backend(out, runner).up(rehearsal)
    assert status == 1 and "no certificate" in output


def test_the_play_runs_from_the_ansible_directory_with_no_proxy_and_the_backends_variables_last(out, runner, rehearsal):
    made = backend(out, runner)
    made.play(rehearsal, "check")
    argv, env, cwd = runner.calls[0]
    assert argv[:4] == ["ansible-playbook", "playbooks/opnsense.yaml", "--check", "--diff"]
    assert argv[4] == "-e" and argv[5] == f"@{out / 'extra-vars.json'}"
    assert json.loads(argv[7]) == {
        "opnsense_gateway_ca_file": str(made.cert),
        "opnsense_gateway_api_port": 8443,
        "opnsense_gateway_credentials_file": str(made.creds),
    }
    assert "HTTPS_PROXY" not in env and env["ANSIBLE_NOCOLOR"] == "1" and cwd == made.repo / "ansible"


def test_an_apply_has_no_check_flag(out, runner, rehearsal):
    backend(out, runner).play(rehearsal, "apply")
    assert "--check" not in runner.calls[0][0]


def test_the_block_playbook_gets_the_rule_and_the_state_as_one_json_value(out, runner, rehearsal):
    made = backend(out, runner)
    made.block(rehearsal, "present")
    argv = runner.calls[0][0]
    assert argv[1].endswith("boundary/block_rule.yaml")
    assert json.loads(argv[3]) == {
        "repo": str(made.repo),
        "ca_file": str(made.cert),
        "api_port": 8443,
        "credentials": str(made.creds),
        "block_source": "192.168.20.0/24",
        "block_destination": "192.168.20.1",
        "block_protocol": "UDP",
        "block_port": 53,
        "block_state": "present",
    }


def test_a_block_step_with_no_rule_fails_without_running_anything(out, runner, rehearsal):
    spec = Spec(rehearsal.name, rehearsal.description, (), {}, None, rehearsal.steps)
    assert backend(out, runner).block(spec, "present")[0] == 1 and runner.calls == []


def test_the_first_flow_step_builds_the_canaries_and_the_next_does_not(out, runner):
    made = backend(out, runner)
    made.flows(("services",), ())
    setup = runner.lines()
    assert (
        "ssh-keygen" in setup[0]
        and f"mkdir -p {REMOTE_DIR}" in setup[1]
        and setup[2].startswith("scp -q")
        and f"scratch_canaries.py up {REMOTE_DIR}/plan.json vmbr9" in setup[3]
    )
    assert json.loads((out / "plan.json").read_text())["runner"]["address"] == "192.168.40.250"
    before = len(runner.calls)
    made.flows((), ("services-gateway-dns",))
    assert len(runner.calls) == before + 1


def test_the_runner_is_called_with_the_selection_and_a_proxy_command_through_the_node(out, runner):
    made = backend(out, runner)
    made.canaries_up = True
    made.flows(("services", "desktops"), ("services-gateway-dns",))
    argv, env, cwd = runner.calls[0]
    assert argv[:3] == [sys.executable, "-m", "network_checks.runner"]
    assert argv[argv.index("--tag") : argv.index("--tag") + 4] == ["--tag", "services", "--tag", "desktops"]
    assert argv[-2:] == ["--flow", "services-gateway-dns"]
    assert f"python3 {REMOTE_DIR}/scratch_canaries.py relay {REMOTE_DIR}/canaries %h %p" in argv[argv.index("--ssh-command") + 1]
    assert (env["PYTHONPATH"], cwd) == (".", made.repo / "tools")


def test_a_canary_setup_step_that_fails_stops_the_setup_and_says_what_it_printed(out, runner):
    runner.rules = {"mkdir": (1, "permission denied\n")}
    status, output = backend(out, runner).flows(("services",), ())
    assert status == 1 and "permission denied" in output and len(runner.calls) == 2


def test_down_removes_the_canaries_before_the_gateway_and_tries_both_when_the_first_fails(out, runner, rehearsal):
    made = backend(out, runner)
    made.up(rehearsal)
    made.canaries_up = True
    runner.calls.clear()
    runner.rules = {"scratch_canaries.py down": (1, "no such namespace\n")}
    status, output = made.down()
    assert status == 1 and "no such namespace" in output
    assert "scratch_canaries.py down" in runner.lines()[0] and runner.lines()[1].endswith(f"down {out}")


def test_down_after_nothing_was_built_runs_nothing(out, runner):
    assert backend(out, runner).down() == (0, "") and runner.calls == []


def test_the_credential_values_and_the_tokens_secret_are_the_secrets(out, runner):
    (out / "credentials.tfvars").write_text('opnsense_root_password = "pw-value-1"\nopnsense_api_key = "key-value-1"\nother = "x"\n')
    assert backend(out, runner).secrets() == ["pw-value-1", "key-value-1", "tok-secret-value"]


def test_run_command_answers_status_and_output_together():
    status, output = run_command([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"])
    assert (status, output) == (3, "out\nerr\n")


def test_run_command_answers_127_for_a_program_that_is_not_there():
    assert run_command(["no-such-program-here"])[0] == 127


def test_run_command_answers_124_when_the_time_runs_out():
    status, output = run_command([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
    assert status == 124 and "timed out after 1 seconds" in output
