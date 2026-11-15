"""The backend that runs the gateway on the Proxmox node, through the repo's own scripts.

It does what an operator does by hand today ([`opnsense-scratch-gateway.md`], [`network-boundary-checks.md`]):
`scratch_gateway.sh up` builds the gateway, the play and the block-rule playbook run from this machine through the
ssh forward, the namespace canaries go up on the node on first use, and the runner reaches them through a
ProxyCommand. `down` removes the canaries and then the gateway. Every command goes through one `Runner`, so the
tests see the argument lists and need no node.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from network_checks.flow_list import load_flow_list
from network_checks.scratch_plan import build_plan, zone_vlans

from scratch_run import canary_vm, gateway_api
from scratch_run.settings import IMAGE_CHECKSUM, IMAGE_URL
from scratch_run.spec import Spec

REPO = Path(__file__).resolve().parents[2]
MGMT_NAME = "OPNsense.internal"
REMOTE_DIR = "/root/scratch-run"  # on the node: the canaries' plan, key and namespaces' state
PROXY_VARS = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")
CREDENTIAL_NAMES = ("opnsense_root_password", "opnsense_root_otp_seed", "opnsense_api_key", "opnsense_api_secret")
TIMEOUT = 3600
TIMED_OUT = 124
# What the gateway's build leaves in the state directory that the results keep (names relative to it; a directory is read file by file).
# The state directory is removed at the end of a clean run, so what is not copied before then is lost.
LOG_FILES = ("build-seed.txt", "init.txt", "apply.txt")
LOG_DIRS = ("update",)
LOG_LIMIT = 200_000  # characters kept of one log, the end of it
DEFAULT_TEMPLATE_VM_ID = "106"  # `tofu/scratch/ubuntu`'s template_vm_id default: the Ubuntu template the VM is cloned from
VM_WAIT_SECONDS = 600  # a cloned VM boots and runs cloud-init before it answers over ssh
VM_POLL_SECONDS = 10


Echo = Callable[[str], None]
ApiGet = Callable[..., tuple[int, str]]


class Runner(Protocol):
    def __call__(
        self, argv: Sequence[str], *, env: Mapping[str, str] | None = None, cwd: Path | None = None, timeout: int = TIMEOUT, on_output: Echo | None = None
    ) -> tuple[int, str]: ...


def run_command(
    argv: Sequence[str], *, env: Mapping[str, str] | None = None, cwd: Path | None = None, timeout: int = TIMEOUT, on_output: Echo | None = None
) -> tuple[int, str]:
    """Run a command and answer with its exit status and its output, standard error included.

    `on_output` gets each line as the command prints it, so a long command can be watched; the answer holds all of it.
    """
    try:
        process = subprocess.Popen(
            list(argv), env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1
        )
    except FileNotFoundError as error:
        return 127, f"{error}\n"
    expired = threading.Event()
    timer = threading.Timer(timeout, lambda: (expired.set(), process.kill()))
    timer.start()
    lines: list[str] = []
    try:
        assert process.stdout is not None  # noqa: S101 - stdout is a pipe
        for line in process.stdout:
            lines.append(line)
            if on_output is not None:
                on_output(line.rstrip("\n"))
        status = process.wait()
    finally:
        timer.cancel()
    if expired.is_set():
        return TIMED_OUT, "".join(lines) + f"timed out after {timeout} seconds: {shlex.join(argv)}\n"
    return status, "".join(lines)


def print_indented(line: str) -> None:
    print(f"    | {line}", flush=True)


def resolve_host(name: str) -> str | None:
    try:
        return socket.gethostbyname(name)
    except OSError:
        return None


class NodeBackend:
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
    ) -> None:
        self.out = out_dir
        self.image_url = image_url
        self.image_checksum = image_checksum
        self.env = dict(env)
        self.run = runner
        self.resolver = resolver
        self.repo = repo
        self.echo = echo
        self.api_get = api_get
        self.sleep = sleep
        self.clock = clock
        self.remembered: list[str] = []
        self.node = env.get("NODE", "")
        self.ansible = env.get("ANSIBLE_PLAYBOOK", "ansible-playbook")
        self.local_port = env.get("LOCAL_PORT", "8443")
        self.lan_bridge = env.get("LAN_BRIDGE", "vmbr9")
        self.vmid = env.get("VM_ID", "501")
        self.gateway_script = repo / "tofu/scratch/opnsense/scratch_gateway.sh"
        self.block_playbook = repo / "tofu/scratch/opnsense/boundary/block_rule.yaml"
        self.cert = out_dir / "first-boot" / "gateway-cert.pem"
        self.creds = out_dir / "credentials.tfvars"
        self.key = out_dir / "runner_key"
        self.canaries_up = False
        self.gateway_started = False
        self.tofu = env.get("TOFU", "tofu")
        self.ubuntu_root = repo / "tofu/scratch/ubuntu"
        self.template_vm_id = env.get("TEMPLATE_VM_ID", "")
        self.vm_wait = int(env.get("VM_WAIT_SECONDS") or VM_WAIT_SECONDS)
        self.vm_tfvars = out_dir / "vm.tfvars.json"
        self.vm_state = out_dir / "vm.tfstate"
        self.vm_zone: str | None = None  # the zone whose canary a VM replaces; its namespace gets no canary address
        self.vm_started = False

    # --- helpers
    def _ssh_opts(self) -> list[str]:
        opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
        control = self.env.get("SSH_CONTROL_PATH")
        return [*opts, "-o", f"ControlPath={control}"] if control else opts

    def _node(self, command: str, timeout: int = 600) -> tuple[int, str]:
        return self.run(["ssh", *self._ssh_opts(), self.node, command], timeout=timeout)

    def _noproxy_env(self) -> dict[str, str]:
        """The collection's modules reach the gateway through the ssh forward, so no proxy may sit in between."""
        env = {key: value for key, value in self.env.items() if key not in PROXY_VARS}
        env["ANSIBLE_NOCOLOR"] = "1"
        env["PYTHONUNBUFFERED"] = "1"  # a Python child buffers a pipe, and the live log would then arrive in blocks
        return env

    def _ansible_vars(self, extra: Mapping[str, object]) -> list[str]:
        values = {
            "opnsense_gateway_ca_file": str(self.cert),
            "opnsense_gateway_api_port": int(self.local_port),
            "opnsense_gateway_credentials_file": str(self.creds),
        }
        return ["-e", json.dumps(values | dict(extra))]

    def _credential(self, name: str) -> str:
        """The value `name` has in the gateway's credentials file, or an empty string."""
        if not self.creds.is_file():
            return ""
        match = re.search(rf'^\s*{name}\s*=\s*"([^"]*)"', self.creds.read_text(), re.MULTILINE)
        return match.group(1) if match else ""

    def release(self) -> str:
        match = re.search(r'^opnsense_gateway_release: "(.*)"$', (self.repo / "ansible/roles/opnsense_gateway/defaults/main.yaml").read_text(), re.MULTILINE)
        return match.group(1) if match else ""

    # --- Backend
    def preflight(self, spec: Spec) -> list[str]:
        problems: list[str] = []
        for name in ("NODE", "PROXMOX_ENDPOINT", "PROXMOX_API_TOKEN"):
            if not self.env.get(name):
                problems.append(f"{name} is not set")
        if not re.fullmatch(r"https://[A-Za-z0-9._~:/%+-]+\.img\.bz2", self.image_url) or "-nano-" not in self.image_url.rsplit("/", 1)[-1]:
            problems.append(f"the image URL must be an https:// URL of an OPNsense nano .img.bz2 file (--image-url, or {IMAGE_URL} in the settings)")
        if not re.fullmatch(r"[0-9a-f]{64}", self.image_checksum):
            problems.append(f"the image checksum must be 64 lowercase hexadecimal characters (--image-checksum, or {IMAGE_CHECKSUM} in the settings)")
        if self.out.resolve().is_relative_to(self.repo.resolve()):
            problems.append(f"OUT_DIR holds credentials and must be outside the repository: {self.out}")
        for tool in ("ssh", "scp", "ssh-keygen", self.ansible, "ansible-galaxy", *((self.tofu,) if spec.canary_vm else ())):
            if shutil.which(tool) is None:
                problems.append(f"{tool} is not installed here")
        if self.resolver(MGMT_NAME) != "127.0.0.1":
            problems.append(f"{MGMT_NAME} must resolve to 127.0.0.1 here; add the line `127.0.0.1 {MGMT_NAME}` to /etc/hosts")
        if spec.vlans and "SEED_VLANS" not in self.gateway_script.read_text():
            problems.append("the spec sets gateway.vlans, and this checkout's scratch_gateway.sh does not take SEED_VLANS")
        if not self.node:
            return problems
        status, _ = self._node("true", timeout=60)
        if status != 0:
            problems.append(f"cannot ssh to {self.node} without a prompt: open a master connection and set SSH_CONTROL_PATH")
            return problems
        if self._node(f"qm status {self.vmid}", timeout=60)[0] == 0:
            problems.append(
                f"VM {self.vmid} exists on the node: a gateway from an earlier run is still there; remove it with "
                f"`qm stop {self.vmid}; qm destroy {self.vmid} --purge`"
            )
        if self._node(f"test -e {REMOTE_DIR}", timeout=60)[0] == 0:
            problems.append(
                f"{REMOTE_DIR} exists on the node: canaries from an earlier run may be up; run "
                f"`python3 {REMOTE_DIR}/scratch_canaries.py down` there, then remove the directory"
            )
        if spec.canary_vm:
            problems += self._canary_vm_problems(spec.canary_vm.zone)
        release = self.release()
        if shutil.which("ansible-galaxy") is not None:
            _, listing = self.run(["ansible-galaxy", "collection", "list", "oxlorg.opnsense", "--format", "json"], timeout=120)
            if f'"{release}"' not in listing:
                problems.append(f"oxlorg.opnsense {release} is not installed: ansible-galaxy collection install -r {self.repo}/ansible/requirements.yml")
        playbook = shutil.which(self.ansible)
        if playbook is not None:
            python = Path(os.path.realpath(playbook)).with_name("python")
            if python.exists() and self.run([str(python), "-c", "import httpx"], timeout=60)[0] != 0:
                problems.append(f"the collection's modules need httpx in ansible's Python: {python} -m pip install httpx")
        return problems

    def _vm_id(self, zone: str) -> int:
        return canary_vm.vm_id(zone, load_flow_list(), zone_vlans())

    def _canary_vm_problems(self, zone: str) -> list[str]:
        """What stops a VM from being built as the canary of `zone`, found on the node."""
        try:
            vm = self._vm_id(zone)
        except ValueError as error:
            return [f"the canary VM cannot be planned: {error}"]
        problems = []
        status, answer = self._node(f"cat /sys/class/net/{self.lan_bridge}/bridge/vlan_filtering", timeout=60)
        if status != 0 or answer.strip() != "1":
            problems.append(
                f"{self.lan_bridge} is not VLAN-aware, and a VM's NIC with a tag needs that: tick VLAN aware on it in the web console and apply the "
                f"change, or point LAN_BRIDGE at an isolated bridge that is (the namespace canaries work on either)"
            )
        template = self.template_vm_id or DEFAULT_TEMPLATE_VM_ID
        if self._node(f"qm status {template}", timeout=60)[0] != 0:
            problems.append(f"the Ubuntu template VM {template} the canary VM is cloned from is not on the node (TEMPLATE_VM_ID names another)")
        if self._node(f"qm status {vm}", timeout=60)[0] == 0:
            problems.append(
                f"VM {vm} exists on the node: a canary VM from an earlier run is still there; remove it with `qm stop {vm}; qm destroy {vm} --purge`"
            )
        return problems

    def up(self, spec: Spec) -> tuple[int, str]:
        self.vm_zone = spec.canary_vm.zone if spec.canary_vm else None
        env = {**self.env, "WANT_VERSION": self.env.get("WANT_VERSION") or self.release()}
        if spec.vlans:
            env["SEED_VLANS"] = ",".join(str(vlan) for vlan in spec.vlans)
        self.out.mkdir(parents=True, exist_ok=True, mode=0o700)  # it will hold the gateway's credentials
        self.gateway_started = True
        status, output = self.run([str(self.gateway_script), "up", str(self.out), self.image_url, self.image_checksum], env=env, on_output=self.echo)
        if status == 0 and not self.cert.is_file():
            return 1, output + f"\nno certificate at {self.cert}\n"
        if status == 0:
            (self.out / "extra-vars.json").write_text(json.dumps(spec.play_vars))
        return status, output

    def play(self, spec: Spec, mode: str) -> tuple[int, str]:
        argv = [self.ansible, "playbooks/opnsense.yaml", "--diff", "-e", f"@{self.out / 'extra-vars.json'}", *self._ansible_vars({})]
        if mode == "check":
            argv.insert(2, "--check")
        return self.run(argv, env=self._noproxy_env(), cwd=self.repo / "ansible", on_output=self.echo)

    def block(self, spec: Spec, state: str) -> tuple[int, str]:
        rule = spec.block_rule
        if rule is None:
            return 1, "the spec has no block_rule\n"
        extra = {"repo": str(self.repo), "ca_file": str(self.cert), "api_port": int(self.local_port), "credentials": str(self.creds)}
        extra |= {
            "block_source": rule.source,
            "block_destination": rule.destination,
            "block_protocol": rule.protocol,
            "block_port": rule.port,
            "block_state": state,
        }
        return self.run([self.ansible, str(self.block_playbook), "-e", json.dumps(extra)], env=self._noproxy_env(), cwd=self.repo, on_output=self.echo)

    def vlans(self, spec: Spec) -> tuple[int, str]:
        url = f"https://{MGMT_NAME}:{self.local_port}/{gateway_api.INTERFACE_LIST_PATH}"
        key, secret = self._credential("opnsense_api_key"), self._credential("opnsense_api_secret")
        if not (key and secret):
            return 1, f"no API credentials in {self.creds}\n"
        status, body = self.api_get(url, cafile=self.cert, key=key, secret=secret)
        passed, verdict = gateway_api.judge_vlans(status, body, spec.vlans)
        return (0 if passed else 1), f"GET /{gateway_api.INTERFACE_LIST_PATH} -> HTTP {status}\n{body.rstrip()}\n{verdict}\n"

    def logs(self) -> dict[str, str]:
        paths = [self.out / name for name in LOG_FILES]
        for name in LOG_DIRS:
            directory = self.out / name
            paths += sorted(directory.iterdir()) if directory.is_dir() else []
        found = {}
        for path in paths:
            if path.is_file():
                text = path.read_text(errors="replace")
                found[path.name if path.parent == self.out else f"{path.parent.name}-{path.name}"] = text[-LOG_LIMIT:]
        return found

    def _runner_ssh(self) -> list[str]:
        """ssh as the runner's key, through the node into the runner's namespace, as the runner's sessions and the wait for the VM use it."""
        proxy = shlex.join(["ssh", *self._ssh_opts(), self.node, f"python3 {REMOTE_DIR}/scratch_canaries.py relay {REMOTE_DIR}/canaries %h %p"])
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

    def _tofu_env(self) -> dict[str, str]:
        return {
            **self.env,
            "TF_IN_AUTOMATION": "1",
            "TF_DATA_DIR": str(self.out / ".terraform-vm"),
            "TF_VAR_proxmox_endpoint": self.env.get("PROXMOX_ENDPOINT", ""),
            "TF_VAR_proxmox_api_token": self.env.get("PROXMOX_API_TOKEN", ""),
            "TF_VAR_proxmox_insecure": self.env.get("PROXMOX_INSECURE", "false"),
        }

    def _tofu(self, *args: str) -> list[str]:
        return [self.tofu, *args, "-input=false"]

    def canary_vm(self, spec: Spec) -> tuple[int, str]:
        if spec.canary_vm is None:
            return 1, "the spec has no canary_vm\n"
        zone = spec.canary_vm.zone
        try:
            vm = self._vm_id(zone)
        except ValueError as error:
            return 1, f"{error}\n"
        transcript = ""
        if not self.canaries_up:
            status, transcript = self._canary_up()
            if status != 0:
                return status, transcript
        try:
            key = canary_vm.public_key_of(Path(f"{self.key}.pub"))
        except (OSError, ValueError) as error:
            return 1, transcript + f"{error}\n"
        self.vm_tfvars.write_text(json.dumps(canary_vm.tfvars(vm, zone, self.lan_bridge, key, self.env.get("NODE_NAME", "pve"), self.template_vm_id)))
        self.vm_started = True  # an apply that failed part-way can leave a VM, so `down` destroys either way
        for argv in (
            [*self._tofu("init"), "-backend=false", "-lockfile=readonly"],
            [*self._tofu("apply"), "-auto-approve", f"-state={self.vm_state}", f"-var-file={self.vm_tfvars}"],
        ):
            status, output = self.run(argv, env=self._tofu_env(), cwd=self.ubuntu_root, on_output=self.echo)
            transcript += f"$ {shlex.join(argv)}\n{output}"
            if status != 0:
                return status, transcript + f"VM {vm} was not built\n"
        address = str(load_flow_list().zones[zone].canary)
        status, waited = self._wait_for_vm(vm, address)
        return status, transcript + waited

    def _wait_for_vm(self, vm: int, address: str) -> tuple[int, str]:
        """Try ssh to the VM through the runner's namespace until it answers or the wait is over."""
        argv = [*self._runner_ssh(), "-o", "ConnectTimeout=10", f"{canary_vm.ADMIN_USER}@{address}", "true"]
        started, log = self.clock(), ""
        while True:
            status, output = self.run(argv, timeout=60)
            waited = self.clock() - started
            if status == 0:
                return 0, log + f"VM {vm} answered over ssh at {address} after {waited:.0f}s\n"
            line = f"ssh to {address} not answered yet after {waited:.0f}s (exit {status}): {output.strip()[-200:]}\n"
            log += line
            if self.echo is not None:
                self.echo(line.rstrip("\n"))
            if waited >= self.vm_wait:
                return 1, log + f"VM {vm} did not answer over ssh at {address} within {self.vm_wait}s\n"
            self.sleep(VM_POLL_SECONDS)

    def _canary_up(self) -> tuple[int, str]:
        """Put the plan, the canaries' script and the runner's key on the node and build the namespaces."""
        self.canaries_up = True
        plan = self.out / "plan.json"
        built = build_plan(load_flow_list(), zone_vlans())
        for zone in built["zones"]:
            if zone["name"] == self.vm_zone:
                zone["canary"] = None  # a VM holds that address
        plan.write_text(json.dumps(built))
        steps: list[Sequence[str]] = [
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.key)],
            ["ssh", *self._ssh_opts(), self.node, f"mkdir -p {REMOTE_DIR}"],
            [
                "scp",
                "-q",
                *self._ssh_opts(),
                str(plan),
                str(self.repo / "tools/network_checks/scratch_canaries.py"),
                f"{self.key}.pub",
                f"{self.node}:{REMOTE_DIR}/",
            ],
            [
                "ssh",
                *self._ssh_opts(),
                self.node,
                f"python3 {REMOTE_DIR}/scratch_canaries.py up {REMOTE_DIR}/plan.json {self.lan_bridge} {REMOTE_DIR}/canaries {REMOTE_DIR}/{self.key.name}.pub",
            ],
        ]
        transcript = ""
        for argv in steps:
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
        if self.vm_zone:
            argv += ["--ssh-user-for", f"{self.vm_zone}={canary_vm.ADMIN_USER}"]
        for tag in tags:
            argv += ["--tag", tag]
        for flow in ids:
            argv += ["--flow", flow]
        status, output = self.run(argv, env={**self.env, "PYTHONPATH": ".", "PYTHONUNBUFFERED": "1"}, cwd=self.repo / "tools", on_output=self.echo)
        return status, transcript + output

    def down(self) -> tuple[int, str]:
        status, transcript = 0, ""
        if self.canaries_up:
            code, output = self.run(
                ["ssh", *self._ssh_opts(), self.node, f"python3 {REMOTE_DIR}/scratch_canaries.py down; rm -rf {REMOTE_DIR}"], timeout=600, on_output=self.echo
            )
            transcript += output
            status = code
        if self.vm_started:
            code, output = self.run(
                [*self._tofu("destroy"), "-auto-approve", f"-state={self.vm_state}", f"-var-file={self.vm_tfvars}"],
                env=self._tofu_env(),
                cwd=self.ubuntu_root,
                on_output=self.echo,
            )
            transcript += output
            status = status or code
        if self.gateway_started:
            self.secrets()  # learn them before the state goes: the engine asks after the removal
            code, output = self.run([str(self.gateway_script), "down", str(self.out)], env=self.env, on_output=self.echo)
            transcript += output
            status = status or code
        if status == 0 and self.gateway_started:
            shutil.rmtree(self.out, ignore_errors=True)  # a removed gateway's credentials and key are worth nothing, and a stale file stops the next run
        return status, transcript

    def secrets(self) -> list[str]:
        values = [*self.remembered, *(value for name in CREDENTIAL_NAMES if (value := self._credential(name)))]
        token = self.env.get("PROXMOX_API_TOKEN", "")
        if "=" in token:
            values.append(token.rsplit("=", 1)[1])
        self.remembered = list(dict.fromkeys(values))
        return self.remembered
