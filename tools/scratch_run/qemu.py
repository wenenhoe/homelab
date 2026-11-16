"""The backend that runs the gateway under QEMU on this machine, on a GitHub-hosted runner or any host with the tools.

The gateway is the pinned OPNsense image, laid out as the Tofu module lays out the VM (`scratch_run.qemu_layout`), booted on a throwaway
qcow2 overlay of the cached image, seeded by the repo's own `build_seed.sh` and `import_seed.py`, and updated by `update_gateway.sh`. Its LAN is
a tap on a host bridge and its WAN is QEMU's user-mode network. The namespace canaries join the same bridge as root, and the play, the block rule
and the API reads reach the gateway at its LAN address, which is what `OPNsense.internal` has to resolve to. Every command goes through one
`Runner`, so the tests see the argument lists and need no QEMU.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from network_checks.flow_list import load_flow_list
from network_checks.scratch_plan import build_plan, zone_vlans

from scratch_run import gateway_api
from scratch_run.engine import MIN_SECRET_LENGTH
from scratch_run.gateway_steps import MGMT_NAME, REPO, ApiGet, Echo, GatewaySteps, Runner, print_indented, resolve_host, run_command
from scratch_run.qemu_layout import STATED, qemu_argv
from scratch_run.spec import Spec

IMAGE_CACHE = "SCRATCH_RUN_IMAGE_CACHE"
QEMU_ACCEL = "SCRATCH_RUN_QEMU_ACCEL"
DEFAULT_IMAGE_CACHE = "~/.cache/scratch-run/image"
LAN_IP = "192.168.77.1"  # the seed's LAN address, as scratch_gateway.sh gives it
HOST_IP = "192.168.77.10"  # this machine's address on the bridge
BRIDGE = "spkbr"
TAP = "spktap"
SEED_DISK = "da1"  # the guest's name for the seed disk
WAN_HOSTNAME = "opn-scratch"
# (boot timeout, step timeout) of the importer, in seconds: software emulation is about 20 times slower than KVM.
IMPORT_TIMEOUTS = {"kvm": (300, 60), "tcg": (1500, 300)}
QEMU_SETTLE_SECONDS = 2  # a QEMU that cannot start exits within this
GATEWAY_TRIES = 90
GATEWAY_WAIT_SECONDS = 2
STOP_SECONDS = 30
REDACTED = "[redacted]"
FAILED_CHECK = ": FAIL"


class Process(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


Spawn = Callable[[Sequence[str], Path], Process]
Connect = Callable[[str, int], bool]


def spawn_process(argv: Sequence[str], log: Path) -> Process:
    """Start a command that keeps running, with what it prints written to `log`."""
    with log.open("wb") as handle:
        return subprocess.Popen(list(argv), stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT)


def tcp_answers(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def kvm_usable() -> bool:
    return os.access("/dev/kvm", os.R_OK | os.W_OK)


class QemuBackend(GatewaySteps):
    # What the build leaves in the state directory that the results keep; the console transcript is read through `logs`, which redacts it.
    LOG_FILES = ("build-seed.txt", "import.txt", "first-boot/console.log", "qemu.txt")
    LOG_DIRS = ("update",)
    DEFAULT_API_PORT = "443"

    def __init__(
        self,
        out_dir: Path,
        image_url: str,
        image_checksum: str,
        env: Mapping[str, str],
        runner: Runner = run_command,
        resolver: Callable[[str], str | None] = resolve_host,
        repo: Path = REPO,
        echo: Echo | None = print_indented,
        api_get: ApiGet = gateway_api.get,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        spawn: Spawn = spawn_process,
        connect: Connect = tcp_answers,
        kvm: Callable[[], bool] = kvm_usable,
        uid: Callable[[], int] = os.getuid,
    ) -> None:
        super().__init__(out_dir, image_url, image_checksum, env, runner, resolver, repo, echo, api_get, sleep, clock)
        self.local_port = "443"  # the gateway's own port: nothing forwards it
        self.spawn = spawn
        self.connect = connect
        self.kvm = kvm
        self.uid = uid
        self.accel = self.env.get(QEMU_ACCEL, "kvm")
        self.cache = Path(self.env.get(IMAGE_CACHE) or DEFAULT_IMAGE_CACHE).expanduser()
        self.seed_dir = out_dir / "seed"
        self.system_disk = out_dir / "system.qcow2"
        self.serial = out_dir / "serial0"
        self.canary_state = out_dir / "canaries"
        self.canaries_script = self.repo / "tools/network_checks/scratch_canaries.py"
        self.build_seed = self.repo / "tofu/modules/proxmox_opnsense_vm/seed/build_seed.sh"
        self.importer = self.repo / "tofu/modules/proxmox_opnsense_vm/first_boot/import_seed.py"
        self.update_script = self.repo / "tofu/scratch/opnsense/update_gateway.sh"
        self.process: Process | None = None
        self.network_started = False
        self.canaries_up = False
        self.gateway_started = False

    # --- helpers
    def _redact(self, text: str) -> str:
        for value in self.secrets():
            if len(value) >= MIN_SECRET_LENGTH:
                text = text.replace(value, REDACTED)
        return text

    def _quiet(self) -> Echo | None:
        """The live echo, with the run's credential values taken out of each line."""
        if self.echo is None:
            return None
        echo = self.echo
        return lambda line: echo(self._redact(line))

    def _mask(self) -> None:
        """Tell the GitHub Actions log to hide each credential value from here on."""
        if self.env.get("GITHUB_ACTIONS") == "true":
            for value in self.secrets():
                print(f"::add-mask::{value}", flush=True)

    def _sudo(self, *argv: str, timeout: int = 120) -> tuple[int, str]:
        return self.run(["sudo", "-n", *argv], timeout=timeout)

    def _runner_ssh(self) -> list[str]:
        """ssh as the runner's key, from the runner's namespace through `relay`, as the runner's sessions use it."""
        proxy = shlex.join(["sudo", "-n", sys.executable, str(self.canaries_script), "relay", str(self.canary_state), "%h", "%p"])
        return [
            "ssh",
            "-i",
            str(self.key),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            f"ProxyCommand={proxy}",
        ]

    # --- Backend
    def preflight(self, spec: Spec) -> list[str]:
        problems = [*self._image_problems(), *self._out_dir_problems()]
        if spec.canary_vm:
            problems.append("a spec with a canary_vm needs a Proxmox node: this backend has namespace canaries only")
        tools = ("qemu-system-x86_64", "qemu-img", "ip", "sudo", "ssh-keygen", "bunzip2", "curl", "openssl", "xmllint", "sfdisk", "mformat", self.ansible)
        problems += self._tool_problems((*tools, "ansible-galaxy"))
        if self.accel not in IMPORT_TIMEOUTS:
            problems.append(f"{QEMU_ACCEL} is {self.accel!r}, which is neither kvm nor tcg")
        elif self.accel == "kvm" and not self.kvm():
            problems.append(
                f"/dev/kvm is not readable and writable by this user; open it (a udev rule, or the kvm group), or set {QEMU_ACCEL}=tcg for software emulation"
            )
        if self._sudo("true", timeout=60)[0] != 0:
            problems.append("sudo needs a password here: the bridge, the tap and the canaries' namespaces need passwordless sudo")
        if self.resolver(MGMT_NAME) != LAN_IP:
            problems.append(f"{MGMT_NAME} must resolve to {LAN_IP} here; add the line `{LAN_IP} {MGMT_NAME}` to /etc/hosts")
        for link in (BRIDGE, TAP):
            if self.run(["ip", "link", "show", link], timeout=60)[0] == 0:
                problems.append(f"the link {link} exists: a run that did not finish left it; remove it with `sudo ip link del {link}`")
        # build_seed.sh hands its options to patch_config.py, which is where `--vlans` is declared.
        if spec.vlans and '"--vlans"' not in self.build_seed.with_name("patch_config.py").read_text():
            problems.append("the spec sets gateway.vlans, and this checkout's seed builder does not take --vlans")
        return problems + self._collection_problems()

    def up(self, spec: Spec) -> tuple[int, str]:
        self.out.mkdir(parents=True, exist_ok=True, mode=0o700)  # it will hold the gateway's credentials
        self.gateway_started = True
        transcript = ""
        for stage in (self._stage_image, lambda: self._seed(spec), self._network, self._boot, self._import_seed, self._wait_for_gateway, self._update):
            status, output = stage()
            transcript += output
            if status != 0:
                return status, transcript
        if not self.cert.is_file():
            return 1, transcript + f"no certificate at {self.cert}\n"
        (self.out / "extra-vars.json").write_text(json.dumps(spec.play_vars))
        return 0, transcript

    def _stage_image(self) -> tuple[int, str]:
        """The unpacked image, from the cache when it is there for this checksum; otherwise downloaded, checked and unpacked once."""
        image, marker = self.cache / "image.raw", self.cache / "image.raw.sha256"
        if image.is_file() and marker.is_file() and marker.read_text().strip() == self.image_checksum:
            return 0, f"the image is cached: {image}\n"
        self.cache.mkdir(parents=True, exist_ok=True)
        packed = self.cache / "image.img.bz2"
        transcript = f"downloading {self.image_url}\n"
        status, output = self.run(["curl", "-sSfL", "--retry", "3", "-o", str(packed), self.image_url], timeout=1800, on_output=self.echo)
        transcript += output
        if status != 0:
            return status, transcript
        with packed.open("rb") as handle:
            got = hashlib.file_digest(handle, "sha256").hexdigest()
        if got != self.image_checksum:
            packed.unlink()
            return 1, transcript + f"the download's SHA-256 is {got}, not the pinned {self.image_checksum}; it was removed\n"
        status, output = self.run(["bunzip2", "-f", str(packed)], timeout=1800, on_output=self.echo)
        transcript += output
        unpacked = self.cache / "image.img"
        if status != 0 or not unpacked.is_file():
            return status or 1, transcript + "the image was not unpacked\n"
        unpacked.replace(image)
        marker.write_text(self.image_checksum + "\n")
        return 0, transcript + f"the image is unpacked: {image}\n"

    def _seed(self, spec: Spec) -> tuple[int, str]:
        """The seed, with credentials made for this run, built as the Tofu module's own script builds it for a node run."""
        argv = [str(self.build_seed), str(self.seed_dir), "--lan-ip", LAN_IP, "--credentials", str(self.creds), "--wan-dhcp-hostname", WAN_HOSTNAME]
        if spec.vlans:
            argv += ["--vlans", ",".join(str(vlan) for vlan in spec.vlans)]
        status, output = self.run(argv, timeout=600)
        (self.out / "build-seed.txt").write_text(output)
        self._mask()
        return status, f"the seed was built (exit {status})\n"

    def _network(self) -> tuple[int, str]:
        """The LAN: a tap on a bridge this machine has an address on."""
        self.network_started = True
        commands = (
            ("ip", "link", "add", BRIDGE, "type", "bridge"),
            ("ip", "addr", "add", f"{HOST_IP}/24", "dev", BRIDGE),
            ("ip", "link", "set", BRIDGE, "up"),
            ("ip", "tuntap", "add", "dev", TAP, "mode", "tap", "user", str(self.uid())),
            ("ip", "link", "set", TAP, "master", BRIDGE),
            ("ip", "link", "set", TAP, "up"),
        )
        for command in commands:
            status, output = self._sudo(*command)
            if status != 0:
                return status, f"`{shlex.join(command)}` failed: {output.strip()}\n"
        return 0, f"the LAN is the tap {TAP} on {BRIDGE} ({HOST_IP}/24)\n"

    def _boot(self) -> tuple[int, str]:
        image = self.cache / "image.raw"
        status, output = self.run(
            ["qemu-img", "create", "-q", "-f", "qcow2", "-b", str(image), "-F", "raw", str(self.system_disk), f"{STATED.disk_gb}G"], timeout=120
        )
        if status != 0:
            return status, f"qemu-img could not make the overlay: {output.strip()}\n"
        argv = qemu_argv(STATED, accel=self.accel, system_disk=self.system_disk, seed_disk=self.seed_dir / "seed.img", serial_socket=self.serial, lan_tap=TAP)
        self.process = self.spawn(argv, self.out / "qemu.txt")
        self.sleep(QEMU_SETTLE_SECONDS)
        if (code := self.process.poll()) is not None:
            tail = (self.out / "qemu.txt").read_text(errors="replace")[-400:] if (self.out / "qemu.txt").is_file() else ""
            return code or 1, f"QEMU exited at once ({code}): {tail.strip()}\n"
        return 0, f"QEMU is running with {self.accel}\n"

    def _import_seed(self) -> tuple[int, str]:
        """Answer the first boot's importer with the repo's own driver, the root password on its standard input."""
        password = self._credential("opnsense_root_password")
        if not password:
            return 1, f"no root password in {self.creds}\n"
        boot, step = IMPORT_TIMEOUTS[self.accel]
        (self.out / "first-boot").mkdir(mode=0o700, exist_ok=True)
        argv = [
            sys.executable,
            "-I",
            str(self.importer),
            "--socket",
            str(self.serial),
            "--seed-disk",
            SEED_DISK,
            "--log",
            str(self.out / "first-boot" / "console.log"),
            "--result",
            str(self.out / "first-boot" / "result.json"),
            "--cert-out",
            str(self.cert),
            "--boot-timeout",
            str(boot),
            "--step-timeout",
            str(step),
        ]
        status, output = self.run(argv, timeout=boot + 600, on_output=self._quiet(), stdin=password + "\n")
        output = self._redact(output)
        (self.out / "import.txt").write_text(output)
        return status, f"the importer exited {status}\n" if status == 0 else f"the importer exited {status}\n{output}"

    def _wait_for_gateway(self) -> tuple[int, str]:
        for _ in range(GATEWAY_TRIES):
            if self.connect(LAN_IP, 443):
                return 0, f"the gateway answers on {LAN_IP}:443\n"
            self.sleep(GATEWAY_WAIT_SECONDS)
        return 1, f"the gateway does not answer on {LAN_IP}:443\n"

    def _update(self) -> tuple[int, str]:
        """Take the gateway to the pinned release through its firmware API, as the node's script does, with the repo's own script."""
        key, secret = self._credential("opnsense_api_key"), self._credential("opnsense_api_secret")
        if not (key and secret):
            return 1, f"no API credentials in {self.creds}\n"
        credentials = self.out / ".gateway.env"
        descriptor = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(f"API_KEY={shlex.quote(key)}\nAPI_SECRET={shlex.quote(secret)}\nLAN_IP={LAN_IP}\n")
        want = self.env.get("WANT_VERSION") or self.release()
        env = {
            **self.env,
            "SERIAL_SOCKET": "",
            "ALLOW_LATEST": self.env.get("ALLOW_LATEST", "0"),
            "UPDATE_TIMEOUT": "1800",
            "UP_TIMEOUT": "900",
            "DOWN_TIMEOUT": "90",
        }
        try:
            status, output = self.run(
                ["bash", str(self.update_script), str(credentials), str(self.cert), want, str(self.out / "update")],
                env=env,
                timeout=3600,
                on_output=self._quiet(),
            )
        finally:
            credentials.unlink(missing_ok=True)
        output = self._redact(output)
        if FAILED_CHECK in output:
            return 1, output + "the update reported failed checks\n"
        return status, output if status == 0 else output + f"the update ended with status {status} and no failed check\n"

    def _canary_up(self) -> tuple[int, str]:
        """The plan, the runner's key and the namespaces, which join the gateway's bridge."""
        self.canaries_up = True
        plan = self.out / "plan.json"
        plan.write_text(json.dumps(build_plan(load_flow_list(), zone_vlans())))
        transcript = ""
        for argv in (
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.key)],
            ["sudo", "-n", sys.executable, str(self.canaries_script), "up", str(plan), BRIDGE, str(self.canary_state), f"{self.key}.pub"],
        ):
            status, output = self.run(argv, timeout=600, on_output=self.echo)
            transcript += f"$ {shlex.join(argv)}\n{output}"
            if status != 0:
                return status, transcript
        return 0, transcript

    def flows(self, tags: tuple[str, ...], ids: tuple[str, ...]) -> tuple[int, str]:
        transcript = ""
        if not self.canaries_up:
            status, transcript = self._canary_up()
            if status != 0:
                return status, transcript
        argv = [sys.executable, "-m", "network_checks.runner", "--ssh-user", "root", "--ssh-command", shlex.join(self._runner_ssh())]
        for tag in tags:
            argv += ["--tag", tag]
        for flow in ids:
            argv += ["--flow", flow]
        status, output = self.run(argv, env={**self.env, "PYTHONPATH": ".", "PYTHONUNBUFFERED": "1"}, cwd=self.repo / "tools", on_output=self.echo)
        return status, transcript + output

    def canary_vm(self, spec: Spec) -> tuple[int, str]:
        return 1, "the QEMU backend has namespace canaries only; a canary VM needs the node backend\n"

    def logs(self) -> dict[str, str]:
        return {name: self._redact(text) for name, text in super().logs().items()}

    def down(self) -> tuple[int, str]:
        status, transcript = 0, ""
        if self.canaries_up:
            status, output = self._sudo(sys.executable, str(self.canaries_script), "down", timeout=600)
            transcript += output
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=STOP_SECONDS)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            transcript += "QEMU was stopped\n"
        if self.network_started:
            for link in (TAP, BRIDGE):
                transcript += self._sudo("ip", "link", "del", link, timeout=60)[1]  # a link that is not there is not a failure
        if self.gateway_started:
            self.secrets()  # learn them before the state goes: the engine asks after the removal
        if status == 0 and self.gateway_started:
            shutil.rmtree(self.out, ignore_errors=True)  # a removed gateway's credentials and key are worth nothing
            with contextlib.suppress(OSError):
                self.serial.unlink()
        return status, transcript
