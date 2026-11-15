from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from scratch_run import node as node_module
from scratch_run.node import REMOTE_DIR, NodeBackend, run_command
from scratch_run.spec import Spec, parse_spec
from scratch_run_fakes import RecordingRunner

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
    assert "HTTPS_PROXY" not in env and env["ANSIBLE_NOCOLOR"] == "1" and env["PYTHONUNBUFFERED"] == "1" and cwd == made.repo / "ansible"


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
    assert (env["PYTHONPATH"], env["PYTHONUNBUFFERED"], cwd) == (".", "1", made.repo / "tools")


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
    status, output = run_command([sys.executable, "-c", "import sys; print('out', flush=True); print('err', file=sys.stderr, flush=True); sys.exit(3)"])
    assert (status, output) == (3, "out\nerr\n")


def test_run_command_answers_127_for_a_program_that_is_not_there():
    assert run_command(["no-such-program-here"])[0] == 127


def test_run_command_answers_124_when_the_time_runs_out():
    status, output = run_command([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
    assert status == 124 and "timed out after 1 seconds" in output


def echo_lines(lines):
    return lines.append


def test_every_long_command_gets_the_echo_so_its_output_can_be_watched(out, runner, rehearsal):
    seen: list[str] = []
    made = NodeBackend(out, URL, SUM, ENV, runner=runner, resolver=lambda name: "127.0.0.1", echo=echo_lines(seen))
    (out / "first-boot").mkdir()
    made.cert.write_text("cert")
    made.up(rehearsal)
    made.play(rehearsal, "apply")
    made.block(rehearsal, "present")
    made.flows(("services",), ())  # the canary setup steps, then the runner
    made.down()
    assert len(runner.calls) == 10 and all(echo is not None for echo in runner.echoed)
    assert all(echo is made.echo for echo in runner.echoed)


def test_a_probe_of_the_node_is_not_echoed(out, runner, rehearsal):
    backend(out, runner).preflight(rehearsal)
    assert runner.calls and all(echo is None for echo in runner.echoed)


def test_up_makes_the_state_directory_for_the_owner_only(out, runner, rehearsal):
    state = out / "state-rehearsal-T"
    made = NodeBackend(state, URL, SUM, ENV, runner=runner, resolver=lambda name: "127.0.0.1")
    made.up(rehearsal)
    assert state.stat().st_mode & 0o077 == 0


def test_a_clean_teardown_removes_the_state_but_the_secrets_stay_known_for_the_scan(out, runner, rehearsal):
    state = out / "state-rehearsal-T"
    state.mkdir()
    (state / "credentials.tfvars").write_text('opnsense_api_secret = "api-secret-1"\n')
    made = NodeBackend(state, URL, SUM, ENV, runner=runner, resolver=lambda name: "127.0.0.1")
    made.gateway_started = True
    assert made.down()[0] == 0
    assert not state.exists()
    assert made.secrets() == ["api-secret-1", "tok-secret-value"]


def test_a_failed_teardown_keeps_the_state_to_clean_up_by_hand(out, runner, rehearsal):
    state = out / "state-rehearsal-T"
    state.mkdir()
    runner.rules = {"scratch_gateway.sh down": (1, "tofu destroy failed")}
    made = NodeBackend(state, URL, SUM, ENV, runner=runner, resolver=lambda name: "127.0.0.1")
    made.gateway_started = True
    runner.rules = {f"{made.gateway_script} down": (1, "tofu destroy failed")}
    assert made.down()[0] == 1 and state.exists()


def test_run_command_hands_each_line_to_the_echo_as_it_is_printed():
    seen: list[str] = []
    script = "import sys, time; print('one', flush=True); time.sleep(0.3); print('two', file=sys.stderr, flush=True)"
    status, output = run_command([sys.executable, "-c", script], on_output=seen.append)
    assert (status, output, seen) == (0, "one\ntwo\n", ["one", "two"])


def test_a_command_that_times_out_still_answers_with_what_it_printed():
    status, output = run_command([sys.executable, "-c", "import time; print('first', flush=True); time.sleep(10)"], timeout=1)
    assert status == 124 and output.startswith("first\n") and "timed out after 1 seconds" in output


def test_the_two_streams_arrive_in_the_order_the_child_wrote_them_when_it_does_not_buffer():
    script = "import sys\nfor n in range(5):\n    print(f'out{n}', flush=True)\n    print(f'err{n}', file=sys.stderr, flush=True)"
    assert run_command([sys.executable, "-c", script])[1].splitlines() == [f"{stream}{n}" for n in range(5) for stream in ("out", "err")]


def test_a_python_child_that_is_not_told_to_stay_unbuffered_holds_its_output_back():
    """Why the backend sets PYTHONUNBUFFERED: without it a Python child's stdout waits for the buffer, a pipe being no terminal."""
    script = "import sys; print('out'); print('err', file=sys.stderr)"
    env = {key: value for key, value in os.environ.items() if key != "PYTHONUNBUFFERED"}
    assert run_command([sys.executable, "-c", script], env=env)[1].splitlines() == ["err", "out"]
    assert run_command([sys.executable, "-c", script], env={**env, "PYTHONUNBUFFERED": "1"})[1].splitlines() == ["out", "err"]


def interface_list(*names: str) -> str:
    return json.dumps({"floating": {"items": [{"value": ""}]}, "interfaces": {"items": [{"value": name, "label": name.upper()} for name in names]}})


class FakeApi:
    """A stand-in for `scratch_run.gateway_api.get` that answers one status and body and records the request."""

    def __init__(self, status: int = 200, body: str = "") -> None:
        self.status, self.body, self.requests = status, body, []

    def __call__(self, url, *, cafile, key, secret, timeout=30):
        self.requests.append({"url": url, "cafile": cafile, "key": key, "secret": secret})
        return self.status, self.body


def vlan_backend(out, runner, api, tags=(20, 30, 40, 50, 60, 70)):
    made = NodeBackend(out, URL, SUM, ENV, runner=runner, resolver=lambda name: "127.0.0.1", api_get=api)
    (out / "credentials.tfvars").write_text('opnsense_api_key = "key-value-1"\nopnsense_api_secret = "secret-value-1"\n')
    spec = Spec("vlans", "d", tuple(tags), {}, None, ())
    return made, spec


def test_the_vlans_step_asks_the_gateway_through_the_forward_with_its_own_key_and_certificate(out, runner):
    api = FakeApi(200, interface_list("lan", "wan", *(f"opt{n}" for n in range(1, 7))))
    made, spec = vlan_backend(out, runner, api)
    status, output = made.vlans(spec)
    assert status == 0, output
    assert api.requests == [
        {"url": "https://OPNsense.internal:8443/api/firewall/filter/get_interface_list", "cafile": made.cert, "key": "key-value-1", "secret": "secret-value-1"}
    ]
    assert runner.calls == []
    assert output.splitlines()[0] == "GET /api/firewall/filter/get_interface_list -> HTTP 200"
    assert output.splitlines()[-1] == "the gateway has 6 VLAN interfaces (opt1, opt2, opt3, opt4, opt5, opt6); the spec seeds 6 VLANs (20, 30, 40, 50, 60, 70)"


def test_the_vlans_step_fails_and_keeps_the_raw_answer_when_the_gateway_has_fewer_interfaces(out, runner):
    body = interface_list("lan", "wan", *(f"opt{n}" for n in range(1, 6)))
    made, spec = vlan_backend(out, runner, FakeApi(200, body))
    status, output = made.vlans(spec)
    assert status == 1
    assert body in output
    assert "the gateway has 5 VLAN interfaces" in output.splitlines()[-1]


def test_the_vlans_step_without_api_credentials_fails_without_asking(out, runner):
    api = FakeApi()
    made, spec = vlan_backend(out, runner, api)
    (out / "credentials.tfvars").write_text("")
    assert made.vlans(spec)[0] == 1
    assert api.requests == []


def test_the_vlans_step_asks_the_port_the_forward_uses(out, runner):
    api = FakeApi(200, interface_list("lan"))
    made = NodeBackend(out, URL, SUM, {**ENV, "LOCAL_PORT": "9443"}, runner=runner, resolver=lambda name: "127.0.0.1", api_get=api)
    (out / "credentials.tfvars").write_text('opnsense_api_key = "key-value-1"\nopnsense_api_secret = "secret-value-1"\n')
    made.vlans(Spec("v", "d", (20,), {}, None, ()))
    assert api.requests[0]["url"].startswith("https://OPNsense.internal:9443/")


def test_the_build_logs_in_the_state_directory_are_handed_over_by_name(out, runner):
    (out / "update").mkdir()
    (out / "update" / "job-update.log").write_text("job ran\n")
    (out / "update" / "fw-status-after.json").write_text('{"status": "error"}')
    (out / "build-seed.txt").write_text("seed built\n")
    (out / "apply.txt").write_text("apply done\n")
    (out / "credentials.tfvars").write_text('opnsense_api_secret = "secret-value-1"\n')
    assert backend(out, runner).logs() == {
        "build-seed.txt": "seed built\n",
        "apply.txt": "apply done\n",
        "update-fw-status-after.json": '{"status": "error"}',
        "update-job-update.log": "job ran\n",
    }


def test_a_gateway_that_never_got_built_has_no_logs(out, runner):
    assert backend(out, runner).logs() == {}


def test_a_log_over_the_limit_is_cut_to_its_end(out, runner):
    (out / "apply.txt").write_text("a" * 300_000 + "the end\n")
    kept = backend(out, runner).logs()["apply.txt"]
    assert len(kept) == 200_000 and kept.endswith("the end\n")


KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItestkey runner@scratch"


@pytest.fixture
def vm_spec() -> Spec:
    return parse_spec(
        {
            "name": "canary-vm",
            "description": "d",
            "canary_vm": {"zone": "services"},
            "steps": [{"id": "vm-up", "vm": "up"}, {"id": "flows", "flows": {"tags": ["services"]}}],
        }
    )


@pytest.fixture
def vm_node(runner) -> RecordingRunner:
    """A node with a VLAN-aware bridge and the Ubuntu template, and neither the gateway's VM nor the canary VM."""
    runner.rules = {"vlan_filtering": (0, "1\n"), "qm status 106": (0, ""), **runner.rules}
    return runner


class Waiting(RecordingRunner):
    """A runner whose ssh to the VM is refused `refusals` times before it answers."""

    def __init__(self, refusals: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.refusals, self.asked = refusals, 0

    def __call__(self, argv, **kwargs):
        if any(word.startswith("scratch@") for word in argv):
            self.calls.append((list(argv), None, None))
            self.asked += 1
            return (255, "Connection refused\n") if self.asked <= self.refusals else (0, "")
        return super().__call__(argv, **kwargs)


def overriding(runner: RecordingRunner, rules: dict[str, tuple[int, str]]) -> dict[str, tuple[int, str]]:
    """`rules` first, so they are matched before the generic ones, and the runner's own rules for the same words dropped."""
    return {**rules, **{word: answer for word, answer in runner.rules.items() if word not in rules}}


def vm_backend(out, runner, spec, env=ENV, **kwargs):
    sleeps: list[float] = []
    made = NodeBackend(out, URL, SUM, env, runner=runner, resolver=lambda name: "127.0.0.1", sleep=sleeps.append, clock=lambda: float(sum(sleeps)), **kwargs)
    made.sleeps = sleeps
    (out / "first-boot").mkdir(exist_ok=True)
    made.cert.write_text("cert")
    made.up(spec)
    (out / "runner_key.pub").write_text(KEY + "\n")  # the key `ssh-keygen` would have written
    runner.calls.clear()
    return made


def test_a_run_with_a_canary_vm_that_can_start_has_no_problem(out, vm_node, vm_spec):
    assert backend(out, vm_node).preflight(vm_spec) == []


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        pytest.param({"vlan_filtering": (0, "0\n")}, "vmbr9 is not VLAN-aware", id="bridge-not-vlan-aware"),
        pytest.param({"vlan_filtering": (1, "cat: no such file")}, "vmbr9 is not VLAN-aware", id="bridge-has-no-such-setting"),
        pytest.param({"qm status 106": (1, "no such VM")}, "template VM 106", id="no-template"),
        pytest.param({"qm status 208": (0, "status: running")}, "VM 208 exists on the node", id="canary-vm-left-from-an-earlier-run"),
    ],
)
def test_what_stops_a_canary_vm_is_named(out, vm_node, vm_spec, rule, message):
    vm_node.rules = overriding(vm_node, rule)
    assert any(message in problem for problem in backend(out, vm_node).preflight(vm_spec))


def test_a_template_vmid_from_the_environment_is_the_one_looked_for(out, vm_node, vm_spec):
    vm_node.rules = overriding(vm_node, {"qm status 9000": (1, "")})
    problems = backend(out, vm_node, env={**ENV, "TEMPLATE_VM_ID": "9000"}).preflight(vm_spec)
    assert any("template VM 9000" in problem for problem in problems)


def test_tofu_is_needed_only_for_a_spec_with_a_canary_vm(out, vm_node, vm_spec, rehearsal, monkeypatch):
    monkeypatch.setattr(node_module.shutil, "which", lambda name: None if name == "tofu" else "/usr/bin/tool")
    assert any("tofu is not installed" in problem for problem in backend(out, vm_node).preflight(vm_spec))
    assert not any("tofu" in problem for problem in backend(out, vm_node).preflight(rehearsal))


def test_a_spec_with_no_canary_vm_does_not_ask_about_the_bridge_or_the_template(out, runner, rehearsal):
    backend(out, runner).preflight(rehearsal)
    assert not any("vlan_filtering" in line or "qm status 106" in line for line in runner.lines())


def test_the_canary_vm_is_built_after_the_namespaces_and_without_the_canary_address_they_would_hold(out, vm_node, vm_spec):
    made = vm_backend(out, vm_node, vm_spec)
    status, output = made.canary_vm(vm_spec)
    assert status == 0, output
    plan = json.loads((out / "plan.json").read_text())
    assert {zone["name"]: zone["canary"] for zone in plan["zones"]}["services"] is None
    assert all(zone["canary"] for zone in plan["zones"] if zone["name"] != "services")
    lines = vm_node.lines()
    order = [
        next(index for index, line in enumerate(lines) if word in line)
        for word in ("ssh-keygen", "scratch_canaries.py up", "init", "apply", "scratch@192.168.20.8")
    ]
    assert order == sorted(order)
    assert output.splitlines()[-1] == "VM 208 answered over ssh at 192.168.20.8 after 0s"


def test_tofu_gets_the_scratch_root_the_state_and_variables_in_the_state_directory_and_the_token_in_its_environment(out, vm_node, vm_spec):
    made = vm_backend(out, vm_node, vm_spec)
    made.canary_vm(vm_spec)
    (init, _, _), (apply, env, cwd) = [call for call in vm_node.calls if call[0][0] == "tofu"]
    assert init == ["tofu", "init", "-input=false", "-backend=false", "-lockfile=readonly"]
    assert apply == ["tofu", "apply", "-input=false", "-auto-approve", f"-state={out / 'vm.tfstate'}", f"-var-file={out / 'vm.tfvars.json'}"]
    assert cwd == made.repo / "tofu/scratch/ubuntu"
    assert (env["TF_VAR_proxmox_api_token"], env["TF_VAR_proxmox_endpoint"], env["TF_DATA_DIR"]) == (
        ENV["PROXMOX_API_TOKEN"],
        ENV["PROXMOX_ENDPOINT"],
        str(out / ".terraform-vm"),
    )
    assert "tok-secret-value" not in " ".join(" ".join(argv) for argv, _, _ in vm_node.calls)
    assert json.loads((out / "vm.tfvars.json").read_text()) == {
        "vm_id": 208,
        "name": "canary-services",
        "lan_bridge": "vmbr9",
        "node_name": "pve",
        "admin_username": "scratch",
        "ssh_public_keys": [KEY],
        "dns_domain": "scratch.lab",
    }


def test_the_vm_is_waited_for_through_the_runners_namespace_as_its_admin_user(out, vm_node, vm_spec):
    made = vm_backend(out, vm_node, vm_spec)
    made.canary_vm(vm_spec)
    argv = next(argv for argv, _, _ in vm_node.calls if "scratch@192.168.20.8" in argv)
    assert argv[-2:] == ["scratch@192.168.20.8", "true"]
    assert argv[argv.index("-i") + 1] == str(out / "runner_key")
    assert f"python3 {REMOTE_DIR}/scratch_canaries.py relay {REMOTE_DIR}/canaries %h %p" in next(word for word in argv if word.startswith("ProxyCommand="))


def test_a_vm_that_answers_late_is_waited_for_and_each_refusal_is_shown(out, vm_spec):
    slow = Waiting(2, rules={"qm status": (1, ""), "test -e": (1, "")})
    shown: list[str] = []
    made = vm_backend(out, slow, vm_spec, echo=shown.append)
    status, output = made.canary_vm(vm_spec)
    assert (status, made.sleeps) == (0, [10, 10])
    assert output.splitlines()[-1] == "VM 208 answered over ssh at 192.168.20.8 after 20s"
    assert len([line for line in shown if "not answered yet" in line]) == 2


def test_a_vm_that_never_answers_fails_after_the_wait_and_says_the_last_refusal(out, vm_spec):
    deaf = Waiting(10**6, rules={"qm status": (1, ""), "test -e": (1, "")})
    made = vm_backend(out, deaf, vm_spec, env={**ENV, "VM_WAIT_SECONDS": "30"})
    status, output = made.canary_vm(vm_spec)
    assert (status, made.sleeps) == (1, [10, 10, 10])
    assert output.splitlines()[-1] == "VM 208 did not answer over ssh at 192.168.20.8 within 30s"
    assert "Connection refused" in output


@pytest.mark.parametrize("word", ["init", "apply"])
def test_a_tofu_step_that_fails_stops_the_build_without_waiting_and_the_vm_is_still_destroyed_at_teardown(out, vm_node, vm_spec, word):
    made = vm_backend(out, vm_node, vm_spec)
    vm_node.rules = overriding(vm_node, {f"tofu {word}": (1, "Error: clone failed\n")})
    status, output = made.canary_vm(vm_spec)
    assert status == 1 and "Error: clone failed" in output and output.splitlines()[-1] == "VM 208 was not built"
    assert not any("scratch@" in line for line in vm_node.lines())
    made.gateway_started = True
    made.down()
    assert any(line.startswith("tofu destroy") for line in vm_node.lines())


def test_a_canary_that_cannot_be_set_up_stops_before_tofu(out, vm_node, vm_spec):
    made = vm_backend(out, vm_node, vm_spec)
    vm_node.rules = overriding(vm_node, {"mkdir": (1, "permission denied\n")})
    status, output = made.canary_vm(vm_spec)
    assert status == 1 and "permission denied" in output
    assert not any(line.startswith("tofu") for line in vm_node.lines())


def test_a_runner_key_that_is_not_there_stops_before_tofu(out, vm_node, vm_spec):
    made = vm_backend(out, vm_node, vm_spec)
    (out / "runner_key.pub").unlink()
    status, _ = made.canary_vm(vm_spec)
    assert status == 1
    assert not any(line.startswith("tofu") for line in vm_node.lines())


def test_a_vm_step_with_no_canary_vm_in_the_spec_runs_nothing(out, vm_node, rehearsal):
    assert backend(out, vm_node).canary_vm(rehearsal) == (1, "the spec has no canary_vm\n")
    assert vm_node.calls == []


def test_the_runner_logs_in_to_the_vms_zone_as_the_vms_admin_user_and_to_the_others_as_root(out, vm_node, vm_spec, rehearsal):
    made = vm_backend(out, vm_node, vm_spec)
    made.canaries_up = True
    made.flows(("services",), ())
    argv = vm_node.calls[-1][0]
    assert argv[argv.index("--ssh-user") + 1] == "root"
    assert argv[argv.index("--ssh-user-for") + 1] == "services=scratch"
    vm_node.calls.clear()
    plain = backend(out, vm_node)
    plain.canaries_up = True
    plain.flows(("services",), ())
    assert "--ssh-user-for" not in vm_node.calls[-1][0]


def test_teardown_removes_the_canaries_then_the_vm_then_the_gateway_and_keeps_the_state_when_the_vm_cannot_be_destroyed(out, vm_node, vm_spec):
    made = vm_backend(out, vm_node, vm_spec)
    made.canary_vm(vm_spec)
    vm_node.calls.clear()
    vm_node.rules = overriding(vm_node, {"tofu destroy": (1, "Error: VM is locked\n")})
    status, output = made.down()
    lines = vm_node.lines()
    assert status == 1 and "VM is locked" in output
    assert "scratch_canaries.py down" in lines[0] and lines[1].startswith("tofu destroy") and lines[2].endswith(f"down {out}")
    assert (out / "vm.tfstate").parent.exists()


def test_a_clean_teardown_of_a_run_with_a_vm_destroys_it_with_the_same_state_and_variables(out, vm_node, vm_spec):
    made = vm_backend(out, vm_node, vm_spec)
    made.canary_vm(vm_spec)
    vm_node.calls.clear()
    assert made.down()[0] == 0
    destroy = next(argv for argv, _, _ in vm_node.calls if argv[:2] == ["tofu", "destroy"])
    assert f"-state={out / 'vm.tfstate'}" in destroy and f"-var-file={out / 'vm.tfvars.json'}" in destroy and "-auto-approve" in destroy
