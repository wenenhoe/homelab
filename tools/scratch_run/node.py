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
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from network_checks.flow_list import load_flow_list
from network_checks.scratch_plan import build_plan, zone_vlans

from scratch_run.settings import IMAGE_CHECKSUM, IMAGE_URL
from scratch_run.spec import Spec

REPO = Path(__file__).resolve().parents[2]
MGMT_NAME = "OPNsense.internal"
REMOTE_DIR = "/root/scratch-run"  # on the node: the canaries' plan, key and namespaces' state
PROXY_VARS = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")
CREDENTIAL_NAMES = ("opnsense_root_password", "opnsense_root_otp_seed", "opnsense_api_key", "opnsense_api_secret")
TIMEOUT = 3600
TIMED_OUT = 124


Echo = Callable[[str], None]


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
    ) -> None:
        self.out = out_dir
        self.image_url = image_url
        self.image_checksum = image_checksum
        self.env = dict(env)
        self.run = runner
        self.resolver = resolver
        self.repo = repo
        self.echo = echo
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
        for tool in ("ssh", "scp", "ssh-keygen", self.ansible, "ansible-galaxy"):
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

    def up(self, spec: Spec) -> tuple[int, str]:
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

    def _canary_up(self) -> tuple[int, str]:
        """Put the plan, the canaries' script and the runner's key on the node and build the namespaces."""
        self.canaries_up = True
        plan = self.out / "plan.json"
        plan.write_text(json.dumps(build_plan(load_flow_list(), zone_vlans())))
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
        proxy = shlex.join(["ssh", *self._ssh_opts(), self.node, f"python3 {REMOTE_DIR}/scratch_canaries.py relay {REMOTE_DIR}/canaries %h %p"])
        ssh_command = shlex.join(
            [
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
        )
        argv = [sys.executable, "-m", "network_checks.runner", "--ssh-user", "root", "--ssh-command", ssh_command]
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
        if self.gateway_started:
            self.secrets()  # learn them before the state goes: the engine asks after the removal
            code, output = self.run([str(self.gateway_script), "down", str(self.out)], env=self.env, on_output=self.echo)
            transcript += output
            status = status or code
        if status == 0 and self.gateway_started:
            shutil.rmtree(self.out, ignore_errors=True)  # a removed gateway's credentials and key are worth nothing, and a stale file stops the next run
        return status, transcript

    def secrets(self) -> list[str]:
        values = list(self.remembered)
        if self.creds.is_file():
            text = self.creds.read_text()
            for name in CREDENTIAL_NAMES:
                match = re.search(rf'^\s*{name}\s*=\s*"([^"]*)"', text, re.MULTILINE)
                if match:
                    values.append(match.group(1))
        token = self.env.get("PROXMOX_API_TOKEN", "")
        if "=" in token:
            values.append(token.rsplit("=", 1)[1])
        self.remembered = list(dict.fromkeys(values))
        return self.remembered
