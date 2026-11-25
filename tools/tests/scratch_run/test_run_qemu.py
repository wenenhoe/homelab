from __future__ import annotations

import hashlib
import json
import re
import shutil
import socket
import sys
import tarfile
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from scratch_run import gateway_steps
from scratch_run import qemu as qemu_module
from scratch_run.engine import EXIT_OK, run
from scratch_run.gateway_steps import REPO
from scratch_run.qemu import BRIDGE, GATEWAY_TRIES, HOST_IP, LAN_IP, SEED_DISK, TAP, WAN_HOSTNAME, QemuBackend, kvm_usable, spawn_process, tcp_answers
from scratch_run.qemu_layout import STATED, qemu_argv
from scratch_run.spec import CanaryVm, Spec
from scratch_run_fakes import FakeProcess, RecordingRunner

REAL_WHICH = shutil.which
PACKED = b"the packed image"
SUM = hashlib.sha256(PACKED).hexdigest()
URL = "https://mirror.example/opnsense/OPNsense-26.1.6-nano-amd64.img.bz2"
PASSWORD, API_KEY, API_SECRET, OTP = "root-password-1", "api-key-value-1", "api-secret-value-1", "otp-seed-value-1"
CREDENTIALS = f'opnsense_root_password = "{PASSWORD}"\nopnsense_api_key = "{API_KEY}"\nopnsense_api_secret = "{API_SECRET}"\nopnsense_root_otp_seed = "{OTP}"\n'
ENV = {"PATH": "/usr/bin", "SCRATCH_RUN_QEMU_ACCEL": "kvm"}


class Machine:
    """What the commands of a run leave behind, as a real machine would: the files each one writes, and how the gateway answers."""

    def __init__(self, out: Path, cache: Path) -> None:
        self.out, self.cache = out, cache
        self.answering = [True]  # does the gateway answer on its port, call by call (the last answer repeats)
        self.sleeps: list[float] = []
        self.processes: list[FakeProcess] = []
        self.spawned: list[tuple[list[str], Path]] = []
        self.importer_output = f"typed {PASSWORD} at the console\n"
        self.runner = RecordingRunner(
            rules={
                "ip link show": (1, "Device does not exist"),
                "curl": self.curl,
                "bunzip2": self.bunzip2,
                "build_seed.sh": self.build_seed,
                "import_seed.py": self.import_seed,
                "update_gateway.sh": (0, "CHECK api: PASS\n"),
            }
        )

    @staticmethod
    def value(argv: list[str], flag: str) -> Path:
        return Path(argv[argv.index(flag) + 1])

    def curl(self, argv: list[str]) -> tuple[int, str]:
        self.value(argv, "-o").write_bytes(PACKED)
        return 0, ""

    def bunzip2(self, argv: list[str]) -> tuple[int, str]:
        packed = Path(argv[-1])
        packed.unlink()
        packed.with_suffix("").write_bytes(b"raw image")
        return 0, ""

    def build_seed(self, argv: list[str]) -> tuple[int, str]:
        self.value(argv, "--credentials").write_text(CREDENTIALS)
        (Path(argv[1]) / "seed.img").parent.mkdir(parents=True, exist_ok=True)
        (Path(argv[1]) / "seed.img").write_bytes(b"seed")
        return 0, "seed built\n"

    def import_seed(self, argv: list[str]) -> tuple[int, str]:
        self.value(argv, "--cert-out").parent.mkdir(parents=True, exist_ok=True)
        self.value(argv, "--cert-out").write_text("certificate")
        self.value(argv, "--log").write_text(f"console transcript with {PASSWORD}\n")
        return 0, self.importer_output

    def spawn(self, argv, log: Path) -> FakeProcess:
        self.spawned.append((list(argv), log))
        log.write_text("qemu started\n")
        process = FakeProcess()
        self.processes.append(process)
        return process

    def connect(self, host: str, port: int) -> bool:
        answer = self.answering.pop(0) if len(self.answering) > 1 else self.answering[0]
        return answer and (host, port) == (LAN_IP, 443)


@pytest.fixture
def cache(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("image-cache")


@pytest.fixture
def out(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("scratch-out")


@pytest.fixture(autouse=True)
def every_tool_is_installed(monkeypatch):
    monkeypatch.setattr(gateway_steps.shutil, "which", create_autospec(REAL_WHICH, return_value="/usr/bin/tool"))


@pytest.fixture
def machine(out, cache) -> Machine:
    return Machine(out, cache)


def backend(machine: Machine, env=None, url=URL, checksum=SUM, kvm=True, resolver=lambda name: LAN_IP, uid=1001) -> QemuBackend:
    made = QemuBackend(
        machine.out,
        url,
        checksum,
        {**ENV, "SCRATCH_RUN_IMAGE_CACHE": str(machine.cache), **(env or {})},
        runner=machine.runner,
        resolver=resolver,
        echo=None,
        sleep=machine.sleeps.append,
        spawn=machine.spawn,
        connect=machine.connect,
        kvm=lambda: kvm,
        uid=lambda: uid,
    )
    machine.runner.rules = machine.runner.rules | {"collection list": (0, f'"{made.release()}"')}
    return made


def words(machine: Machine) -> list[str]:
    return machine.runner.lines()


def first(machine: Machine, word: str) -> int:
    return next(index for index, line in enumerate(words(machine)) if word in line)


# --- preflight
def test_a_machine_with_everything_can_start_a_run(machine, rehearsal):
    assert backend(machine).preflight(rehearsal) == []


def test_every_missing_precondition_is_named_in_one_pass(machine, rehearsal, monkeypatch):
    monkeypatch.setattr(gateway_steps.shutil, "which", create_autospec(REAL_WHICH, return_value=None))
    machine.runner.rules = {"sudo": (1, "a password is required"), "ip link show": (0, "exists")}
    spec = Spec(rehearsal.name, rehearsal.description, (), {}, None, rehearsal.steps[:1], rehearsal_canary_vm())
    problems = " | ".join(backend(machine, url="http://bad/url", checksum="XYZ", kvm=False, resolver=lambda name: None).preflight(spec))
    for part in (
        "image URL must be an https",
        "image checksum must be 64",
        "canary_vm needs a Proxmox node",
        "qemu-system-x86_64 is not installed",
        "/dev/kvm is not readable",
        "sudo needs a password",
        f"must resolve to {LAN_IP}",
        f"the link {BRIDGE} exists",
        f"the link {TAP} exists",
    ):
        assert part in problems


def rehearsal_canary_vm():

    return CanaryVm("services")


def test_software_emulation_needs_no_kvm(machine, rehearsal):
    assert backend(machine, env={"SCRATCH_RUN_QEMU_ACCEL": "tcg"}, kvm=False).preflight(rehearsal) == []


def test_an_accelerator_that_is_neither_kvm_nor_tcg_is_refused(machine, rehearsal):
    assert any("'hvf', which is neither kvm nor tcg" in problem for problem in backend(machine, env={"SCRATCH_RUN_QEMU_ACCEL": "hvf"}).preflight(rehearsal))


def test_an_out_dir_inside_the_repository_is_refused(rehearsal, machine):
    made = QemuBackend(REPO / "scratch-out", URL, SUM, ENV, runner=machine.runner, resolver=lambda name: LAN_IP, kvm=lambda: True)
    assert any("must be outside the repository" in problem for problem in made.preflight(rehearsal))


def test_the_collection_is_checked(machine, rehearsal):
    made = backend(machine)
    machine.runner.rules = machine.runner.rules | {"collection list": (0, "[]")}
    assert any(re.search("oxlorg.opnsense .* is not installed", problem) for problem in made.preflight(rehearsal))


def test_a_spec_that_sets_vlans_needs_a_seed_builder_that_takes_them(machine, rehearsal, tmp_path):
    spec = Spec(rehearsal.name, rehearsal.description, (20, 70), {}, None, rehearsal.steps[:1])
    (tmp_path / "build_seed.sh").write_text("#!/bin/sh\n")
    options = tmp_path / "patch_config.py"
    options.write_text('ap.add_argument("--lan-ip")\n')
    made = backend(machine)
    made.build_seed = tmp_path / "build_seed.sh"
    assert any("does not take --vlans" in problem for problem in made.preflight(spec))
    options.write_text('ap.add_argument("--vlans")\n')
    assert not any("--vlans" in problem for problem in made.preflight(spec))


def test_the_seed_builder_of_this_checkout_takes_the_vlans_a_spec_sets(machine, rehearsal):
    spec = Spec(rehearsal.name, rehearsal.description, (20, 70), {}, None, rehearsal.steps[:1])
    assert backend(machine).preflight(spec) == []


# --- up
def test_up(machine, rehearsal):
    made = backend(machine)
    status, transcript = made.up(rehearsal)
    assert status == 0, transcript
    order = [first(machine, word) for word in ("curl", "bunzip2", "build_seed.sh", "ip link add", "qemu-img", "import_seed.py", "update_gateway.sh")]
    assert order == sorted(order)
    assert json.loads((machine.out / "extra-vars.json").read_text()) == rehearsal.play_vars
    assert made.cert.read_text() == "certificate"


def test_the_image_is_downloaded_checked_and_unpacked_once_into_the_cache(machine, rehearsal):
    backend(machine).up(rehearsal)
    argv = machine.runner.calls[first(machine, "curl")][0]
    assert argv == ["curl", "-sSfL", "--retry", "3", "-o", str(machine.cache / "image.img.bz2"), URL]
    assert (machine.cache / "image.raw").read_bytes() == b"raw image"
    assert (machine.cache / "image.raw.sha256").read_text() == SUM + "\n"
    assert not (machine.cache / "image.img.bz2").exists()


def test_a_cached_image_for_this_checksum_is_neither_downloaded_nor_unpacked(machine, rehearsal):
    machine.cache.mkdir(exist_ok=True)
    (machine.cache / "image.raw").write_bytes(b"raw image")
    (machine.cache / "image.raw.sha256").write_text(SUM + "\n")
    backend(machine).up(rehearsal)
    assert not any(word in line for line in words(machine) for word in ("curl", "bunzip2"))


def test_a_cached_image_for_another_checksum_is_replaced(machine, rehearsal):
    machine.cache.mkdir(exist_ok=True)
    (machine.cache / "image.raw").write_bytes(b"older image")
    (machine.cache / "image.raw.sha256").write_text("b" * 64 + "\n")
    backend(machine).up(rehearsal)
    assert ((machine.cache / "image.raw").read_bytes(), (machine.cache / "image.raw.sha256").read_text()) == (b"raw image", SUM + "\n")


def test_a_download_that_does_not_match_the_pin_is_removed_and_stops_the_run(machine, rehearsal):
    status, transcript = backend(machine, checksum="c" * 64).up(rehearsal)
    assert status == 1
    assert f"not the pinned {'c' * 64}" in transcript
    assert not (machine.cache / "image.img.bz2").exists()
    assert not any("build_seed.sh" in line for line in words(machine))


def test_a_failed_download_stops_the_run(machine, rehearsal):
    machine.runner.rules = machine.runner.rules | {"curl": (22, "HTTP 404")}
    status, transcript = backend(machine).up(rehearsal)
    assert (status, "HTTP 404" in transcript) == (22, True)
    assert not any("bunzip2" in line for line in words(machine))


def test_the_seed_is_built_as_the_node_scripts_build_it(machine, rehearsal):
    spec = Spec(rehearsal.name, rehearsal.description, (20, 70), rehearsal.play_vars, rehearsal.block_rule, rehearsal.steps)
    made = backend(machine)
    made.up(spec)
    argv = machine.runner.calls[first(machine, "build_seed.sh")][0]
    assert argv[1:] == [
        str(machine.out / "seed"),
        "--lan-ip",
        LAN_IP,
        "--credentials",
        str(made.creds),
        "--operator-host",
        HOST_IP,
        "--wan-dhcp-hostname",
        WAN_HOSTNAME,
        "--vlans",
        "20,70",
    ]


def test_a_spec_without_vlans_leaves_the_seeds_own_list(machine, rehearsal):
    backend(machine).up(rehearsal)
    assert "--vlans" not in machine.runner.calls[first(machine, "build_seed.sh")][0]


def test_the_lan_is_a_tap_on_a_bridge_this_machine_has_an_address_on(machine, rehearsal):
    backend(machine, uid=1234).up(rehearsal)
    network = [line for line in words(machine) if line.startswith("sudo -n ip ")]
    assert network == [
        f"sudo -n ip link add {BRIDGE} type bridge",
        f"sudo -n ip addr add {HOST_IP}/24 dev {BRIDGE}",
        f"sudo -n ip link set {BRIDGE} up",
        f"sudo -n ip tuntap add dev {TAP} mode tap user 1234",
        f"sudo -n ip link set {TAP} master {BRIDGE}",
        f"sudo -n ip link set {TAP} up",
    ]


def test_a_command_of_the_network_that_fails_stops_the_run_before_qemu(machine, rehearsal):
    machine.runner.rules = machine.runner.rules | {"tuntap": (1, "Operation not permitted")}
    status, transcript = backend(machine).up(rehearsal)
    assert status == 1 and "Operation not permitted" in transcript
    assert machine.spawned == []


def test_the_overlay_is_the_modules_size_and_qemu_gets_the_command_line_the_layout_builds(machine, rehearsal):
    made = backend(machine)
    made.up(rehearsal)
    overlay = machine.runner.calls[first(machine, "qemu-img")][0]
    assert overlay == [
        "qemu-img",
        "create",
        "-q",
        "-f",
        "qcow2",
        "-b",
        str(machine.cache / "image.raw"),
        "-F",
        "raw",
        str(made.system_disk),
        f"{STATED.disk_gb}G",
    ]
    ((argv, log),) = machine.spawned
    assert argv == qemu_argv(
        STATED, accel="kvm", system_disk=made.system_disk, seed_disk=machine.out / "seed" / "seed.img", serial_socket=made.serial, lan_tap=TAP
    )
    assert log == machine.out / "qemu.txt"


def test_software_emulation_boots_with_tcg_and_waits_longer_for_the_importer(machine, rehearsal):
    backend(machine, env={"SCRATCH_RUN_QEMU_ACCEL": "tcg"}, kvm=False).up(rehearsal)
    qemu_args = machine.spawned[0][0]
    importer = machine.runner.calls[first(machine, "import_seed.py")][0]
    assert (qemu_args[qemu_args.index("-accel") + 1], importer[importer.index("--boot-timeout") + 1], importer[importer.index("--step-timeout") + 1]) == (
        "tcg",
        "1500",
        "300",
    )


def test_a_qemu_that_exits_at_once_stops_the_run_with_what_it_printed(machine, rehearsal):
    def dies(argv, log):
        log.write_text("qemu-system-x86_64: Could not access KVM kernel module\n")
        process = FakeProcess(exit_code=1)
        machine.processes.append(process)
        return process

    made = backend(machine)
    made.spawn = dies
    status, transcript = made.up(rehearsal)
    assert status == 1 and "Could not access KVM kernel module" in transcript
    assert not any("import_seed.py" in line for line in words(machine))


def test_the_importer_gets_the_password_on_its_standard_input_and_never_in_its_arguments(machine, rehearsal):
    made = backend(machine)
    made.up(rehearsal)
    index = first(machine, "import_seed.py")
    argv = machine.runner.calls[index][0]
    assert machine.runner.stdins[index] == PASSWORD + "\n"
    assert PASSWORD not in " ".join(argv)
    assert argv[:3] == [sys.executable, "-I", str(REPO / "tofu/modules/proxmox_opnsense_vm/first_boot/import_seed.py")]
    assert (argv[argv.index("--socket") + 1], argv[argv.index("--seed-disk") + 1], argv[argv.index("--cert-out") + 1]) == (
        str(made.serial),
        SEED_DISK,
        str(made.cert),
    )
    assert (argv[argv.index("--boot-timeout") + 1], argv[argv.index("--step-timeout") + 1]) == ("300", "60")


def test_a_failed_importer_stops_the_run_and_its_output_holds_no_credential(machine, rehearsal):
    machine.runner.rules = machine.runner.rules | {"import_seed.py": lambda argv: (4, machine.importer_output)}
    status, transcript = backend(machine).up(rehearsal)
    assert status == 4
    assert PASSWORD not in transcript and "[redacted]" in transcript
    assert not any("update_gateway.sh" in line for line in words(machine))
    assert PASSWORD not in (machine.out / "import.txt").read_text()


def test_the_live_echo_of_the_importer_is_redacted(machine, rehearsal):
    shown: list[str] = []
    made = backend(machine)
    made.echo = shown.append
    made.up(rehearsal)
    echo = machine.runner.echoed[first(machine, "import_seed.py")]
    echo(f"the password is {PASSWORD}")
    assert shown[-1] == "the password is [redacted]"


def test_a_gateway_that_never_answers_stops_the_run_after_its_tries(machine, rehearsal):
    machine.answering = [False]
    status, transcript = backend(machine).up(rehearsal)
    assert status == 1 and f"does not answer on {LAN_IP}:443" in transcript
    assert machine.sleeps == [qemu_module.QEMU_SETTLE_SECONDS] + [qemu_module.GATEWAY_WAIT_SECONDS] * GATEWAY_TRIES
    assert not any("update_gateway.sh" in line for line in words(machine))


def test_a_gateway_that_answers_late_is_waited_for(machine, rehearsal):
    machine.answering = [False, False, True]
    assert backend(machine).up(rehearsal)[0] == 0
    assert machine.sleeps == [qemu_module.QEMU_SETTLE_SECONDS] + [qemu_module.GATEWAY_WAIT_SECONDS] * 2


def test_the_update_gets_the_credentials_in_a_file_that_is_gone_afterwards(machine, rehearsal):
    made = backend(machine, env={"ALLOW_LATEST": "1"})
    seen: list[str] = []

    def update(argv):
        seen.append(Path(argv[2]).read_text())
        seen.append(oct(Path(argv[2]).stat().st_mode & 0o777))
        return 0, "CHECK api: PASS\n"

    machine.runner.rules = machine.runner.rules | {"update_gateway.sh": update}
    made.up(rehearsal)
    index = first(machine, "update_gateway.sh")
    argv, env, _ = machine.runner.calls[index]
    assert seen == [f"API_KEY={API_KEY}\nAPI_SECRET={API_SECRET}\nLAN_IP={LAN_IP}\n", "0o600"]
    assert argv == ["bash", str(made.update_script), str(machine.out / ".gateway.env"), str(made.cert), made.release(), str(machine.out / "update")]
    assert (env["SERIAL_SOCKET"], env["ALLOW_LATEST"], env["UPDATE_TIMEOUT"], env["UP_TIMEOUT"], env["DOWN_TIMEOUT"]) == ("", "1", "1800", "900", "90")
    assert not (machine.out / ".gateway.env").exists()


def test_the_pinned_release_is_overridden_by_want_version(machine, rehearsal):
    backend(machine, env={"WANT_VERSION": "26.1.99"}).up(rehearsal)
    assert machine.runner.calls[first(machine, "update_gateway.sh")][0][4] == "26.1.99"


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        pytest.param((0, "CHECK api: FAIL\n"), 1, id="failed-check-with-a-zero-exit"),
        pytest.param((2, "CHECK api: FAIL\nCHECK x: FAIL\n"), 1, id="failed-checks"),
        pytest.param((124, "no check at all\n"), 124, id="no-check-and-a-bad-exit"),
    ],
)
def test_an_update_that_fails_stops_the_run(machine, rehearsal, answer, status):
    machine.runner.rules = machine.runner.rules | {"update_gateway.sh": answer}
    assert backend(machine).up(rehearsal)[0] == status


def test_a_run_that_leaves_no_certificate_fails(machine, rehearsal):
    machine.runner.rules = machine.runner.rules | {"import_seed.py": (0, "")}
    status, transcript = backend(machine).up(rehearsal)
    assert status == 1 and "no certificate" in transcript


def test_the_credential_values_are_masked_in_a_github_actions_log_once_they_exist(machine, rehearsal, capsys):
    backend(machine, env={"GITHUB_ACTIONS": "true"}).up(rehearsal)
    printed = capsys.readouterr().out.splitlines()
    assert sorted(line for line in printed if line.startswith("::add-mask::")) == sorted(
        f"::add-mask::{value}" for value in (PASSWORD, API_KEY, API_SECRET, OTP)
    )


def test_nothing_is_masked_outside_github_actions(machine, rehearsal, capsys):
    backend(machine).up(rehearsal)
    assert "::add-mask::" not in capsys.readouterr().out


# --- steps that reach the gateway
def test_the_play_reaches_the_gateway_at_its_own_port(machine, rehearsal):
    made = backend(machine)
    made.play(rehearsal, "check")
    argv = machine.runner.calls[-1][0]
    assert json.loads(argv[7])["opnsense_gateway_api_port"] == 443


def test_the_first_flows_step_builds_the_canaries_on_the_gateways_bridge_and_a_later_one_does_not(machine, rehearsal):
    made = backend(machine)
    made.flows(("services",), ())
    made.flows((), ("services-gateway-dns",))
    keygen = [line for line in words(machine) if line.startswith("ssh-keygen")]
    canaries = [line for line in words(machine) if "scratch_canaries.py up" in line]
    assert (len(keygen), len(canaries)) == (1, 1)
    assert canaries[0] == (f"sudo -n {sys.executable} {made.canaries_script} up {machine.out / 'plan.json'} {BRIDGE} {machine.out / 'canaries'} {made.key}.pub")
    assert json.loads((machine.out / "plan.json").read_text())["zones"]


def test_the_runner_reaches_the_canaries_through_relay_as_root(machine, rehearsal):
    made = backend(machine)
    made.flows(("services",), ("services-gateway-dns",))
    argv, env, cwd = machine.runner.calls[-1]
    assert argv[:3] == [sys.executable, "-m", "network_checks.runner"]
    assert (argv[argv.index("--tag") + 1], argv[argv.index("--flow") + 1], argv[argv.index("--ssh-user") + 1]) == ("services", "services-gateway-dns", "root")
    command = argv[argv.index("--ssh-command") + 1]
    assert f"-i {made.key}" in command and f"sudo -n {sys.executable} {made.canaries_script} relay {machine.out / 'canaries'} %h %p" in command
    assert (cwd, env["PYTHONPATH"]) == (REPO / "tools", ".")


def test_canaries_that_fail_to_build_stop_the_flows(machine, rehearsal):
    machine.runner.rules = machine.runner.rules | {"scratch_canaries.py up": (1, "no sshd")}
    status, output = backend(machine).flows(("services",), ())
    assert status == 1 and "no sshd" in output
    assert not any("network_checks.runner" in line for line in words(machine))


def test_a_canary_vm_is_not_built(machine, rehearsal):
    status, output = backend(machine).canary_vm(rehearsal)
    assert status == 1 and "namespace canaries only" in output


# --- what is kept and what is removed
def test_the_logs_kept_are_redacted(machine, rehearsal):
    made = backend(machine)
    made.up(rehearsal)
    (machine.out / "update").mkdir()
    (machine.out / "update" / "job.log").write_text(f"key {API_KEY}\n")
    logs = made.logs()
    assert {"build-seed.txt", "import.txt", "first-boot-console.log", "qemu.txt", "update-job.log"} <= set(logs)
    assert "[redacted]" in logs["first-boot-console.log"] and "[redacted]" in logs["update-job.log"]
    assert not any(value in text for text in logs.values() for value in (PASSWORD, API_KEY, API_SECRET, OTP))


def test_down_stops_the_canaries_then_qemu_then_removes_the_links_and_the_state(machine, rehearsal):
    made = backend(machine)
    made.up(rehearsal)
    made.flows(("services",), ())
    machine.runner.calls.clear()
    status, _ = made.down()
    assert status == 0
    assert words(machine) == [
        f"sudo -n {sys.executable} {made.canaries_script} down",
        f"sudo -n ip link del {TAP}",
        f"sudo -n ip link del {BRIDGE}",
    ]
    assert machine.processes[0].terminated and not machine.processes[0].killed
    assert not machine.out.exists()


def test_a_qemu_that_does_not_stop_is_killed(machine, rehearsal):
    made = backend(machine)
    made.up(rehearsal)
    machine.processes[0].stuck = True
    made.down()
    assert machine.processes[0].killed


def test_the_state_stays_when_the_canaries_could_not_be_removed(machine, rehearsal):
    made = backend(machine)
    made.up(rehearsal)
    made.flows(("services",), ())
    machine.runner.rules = machine.runner.rules | {"scratch_canaries.py down": (1, "busy")}
    status, _ = made.down()
    assert status == 1 and machine.out.exists()


def test_down_after_a_run_that_never_started_touches_nothing(machine):
    assert backend(machine).down() == (0, "")
    assert machine.runner.calls == []


def test_down_after_an_up_that_stopped_early_removes_what_it_made(machine, rehearsal):
    machine.runner.rules = machine.runner.rules | {"tuntap": (1, "denied")}
    made = backend(machine)
    made.up(rehearsal)
    machine.runner.calls.clear()
    made.down()
    assert words(machine) == [f"sudo -n ip link del {TAP}", f"sudo -n ip link del {BRIDGE}"]


def test_the_secrets_stay_known_after_the_state_is_removed(machine, rehearsal):
    made = backend(machine)
    made.up(rehearsal)
    made.down()
    assert set(made.secrets()) == {PASSWORD, API_KEY, API_SECRET, OTP}


# --- the whole run through the engine
def test_a_run_through_the_engine_ends_with_an_archive_that_holds_no_credential(machine, rehearsal, tmp_path_factory):
    results = tmp_path_factory.mktemp("results")
    spec = Spec(rehearsal.name, rehearsal.description, (), {}, None, rehearsal.steps[:1])
    messages: list[str] = []
    made = backend(machine)
    made.echo = messages.append
    machine.runner.rules = machine.runner.rules | {"ansible-playbook": (0, "ok\n")}
    code = run(spec, made, results, "20261116-120000", clock=iter(range(0, 1000, 5)).__next__, say=messages.append)
    assert code == EXIT_OK, "\n".join(messages)
    archive = results / f"results-{spec.name}-20261116-120000.tgz"
    with tarfile.open(archive) as tar:
        texts = {member.name: tar.extractfile(member).read().decode() for member in tar.getmembers() if member.isfile()}
    assert {name.split("/", 1)[1] for name in texts} >= {"up.txt", "down.txt", "results.json", "logs/import.txt", "logs/first-boot-console.log"}
    assert not any(value in text for text in texts.values() for value in (PASSWORD, API_KEY, API_SECRET, OTP))
    assert not machine.out.exists()


# --- the real helpers
def test_a_process_is_started_with_its_output_in_a_file(tmp_path):
    log = tmp_path / "out.txt"
    process = spawn_process([sys.executable, "-c", "print('hello from qemu')"], log)
    assert process.wait(timeout=30) == 0
    assert log.read_text() == "hello from qemu\n"


def test_a_port_that_accepts_connections_answers_and_one_that_does_not_does_not():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert tcp_answers("127.0.0.1", port) is True
    assert tcp_answers("127.0.0.1", port) is False


@pytest.mark.parametrize("usable", [True, False], ids=["usable", "not-usable"])
def test_kvm_is_usable_when_the_device_can_be_read_and_written(monkeypatch, usable):
    monkeypatch.setattr(qemu_module.os, "access", create_autospec(qemu_module.os.access, return_value=usable))
    assert kvm_usable() is usable


def test_a_command_given_standard_input_gets_it_and_one_that_closes_early_does_not_break_the_run():
    status, output = gateway_steps.run_command([sys.executable, "-c", "import sys; print(sys.stdin.readline().strip().upper())"], stdin="secret\n", timeout=30)
    assert (status, output) == (0, "SECRET\n")
    status, _ = gateway_steps.run_command([sys.executable, "-c", "pass"], stdin="x" * 1_000_000, timeout=30)
    assert status == 0


# --- the layout the script states and the files this backend answers to
def read(path: str) -> str:
    return (REPO / path).read_text()


def test_the_lan_addresses_are_those_scratch_gateway_sh_gives_the_seed_and_the_node():
    script = read("tofu/scratch/opnsense/scratch_gateway.sh")
    assert f"lan_ip={LAN_IP}\n" in script and f"node_ip={HOST_IP}\n" in script


def test_the_seed_is_built_with_the_flags_scratch_gateway_sh_gives_it():
    line = next(line for line in read("tofu/scratch/opnsense/scratch_gateway.sh").splitlines() if "build_seed.sh" in line)
    assert f'--lan-ip "$lan_ip" --credentials "$creds" --operator-host "$node_ip" --wan-dhcp-hostname {WAN_HOSTNAME}' in line and '"${seed_list[@]}"' in line
    script = read("tofu/scratch/opnsense/scratch_gateway.sh")
    assert "seed_list=(--scratch)" in script and 'seed_list=(--vlans "$seed_vlans")' in script


def test_the_seed_disk_is_the_one_first_boot_sh_answers_the_importer_with():
    assert f"seed_disk=${{SEED_DISK:-{SEED_DISK}}}" in read("tofu/modules/proxmox_opnsense_vm/first_boot/first_boot.sh")


def test_every_flag_the_importer_is_given_is_one_it_takes():
    importer = read("tofu/modules/proxmox_opnsense_vm/first_boot/import_seed.py")
    for flag in ("--socket", "--seed-disk", "--log", "--result", "--cert-out", "--boot-timeout", "--step-timeout"):
        assert f'"{flag}"' in importer


def test_every_variable_the_update_is_given_is_one_the_script_reads():
    script = read("tofu/scratch/opnsense/update_gateway.sh")
    for variable in ("SERIAL_SOCKET", "ALLOW_LATEST", "UPDATE_TIMEOUT", "UP_TIMEOUT", "DOWN_TIMEOUT", "UP_PROBE_TIMEOUT"):
        assert variable in script


def test_the_canaries_script_takes_the_commands_the_backend_gives_it():
    usage = read("tools/network_checks/scratch_canaries.py")
    for command in (
        "scratch_canaries.py up PLAN.json BRIDGE STATE_DIR AUTHORIZED_KEY.pub",
        "scratch_canaries.py down",
        "scratch_canaries.py relay STATE_DIR HOST PORT",
    ):
        assert command in usage
