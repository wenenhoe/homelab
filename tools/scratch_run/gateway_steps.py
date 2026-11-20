"""What the backends share: how a command is run, and the steps that reach the gateway through its API and the play.

A backend differs in where the gateway runs, how it is built and removed, and how the canaries reach it. The play, the block-rule
playbook, the API reads, the logs and the credential values are the same from this machine to either gateway, so `GatewaySteps` holds them once.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from scratch_run import gateway_api
from scratch_run.image_pin import image_problems
from scratch_run.spec import Spec

REPO = Path(__file__).resolve().parents[2]
MGMT_NAME = "OPNsense.internal"
PROXY_VARS = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")
CREDENTIAL_NAMES = ("opnsense_root_password", "opnsense_root_otp_seed", "opnsense_api_key", "opnsense_api_secret")
TIMEOUT = 3600
TIMED_OUT = 124
LOG_LIMIT = 200_000  # characters kept of one log, the end of it

Echo = Callable[[str], None]
ApiGet = Callable[..., tuple[int, str]]


class Runner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        timeout: int = TIMEOUT,
        on_output: Echo | None = None,
        stdin: str | None = None,
    ) -> tuple[int, str]: ...


def run_command(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    timeout: int = TIMEOUT,
    on_output: Echo | None = None,
    stdin: str | None = None,
) -> tuple[int, str]:
    """Run a command and answer with its exit status and its output, standard error included.

    `on_output` gets each line as the command prints it, so a long command can be watched; the answer holds all of it. `stdin` is written
    to the command and closed, which is how a secret reaches one without being in its argument list.
    """
    try:
        process = subprocess.Popen(
            list(argv),
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL if stdin is None else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
    except FileNotFoundError as error:
        return 127, f"{error}\n"
    if stdin is not None:
        assert process.stdin is not None  # noqa: S101 - stdin is a pipe
        with contextlib.suppress(BrokenPipeError):
            process.stdin.write(stdin)
            process.stdin.close()
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


class GatewaySteps:
    """The steps both backends run the same way. A backend sets `LOG_FILES` and `LOG_DIRS`, the names under its state directory that the results keep.

    The state directory is removed at the end of a clean run, so what is not copied by `logs` before then is lost.
    """

    LOG_FILES: tuple[str, ...] = ()
    LOG_DIRS: tuple[str, ...] = ()
    DEFAULT_API_PORT = "8443"

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
        self.ansible = self.env.get("ANSIBLE_PLAYBOOK", "ansible-playbook")
        self.local_port = self.env.get("LOCAL_PORT", self.DEFAULT_API_PORT)
        self.block_playbook = repo / "tofu/scratch/opnsense/boundary/block_rule.yaml"
        self.stray_playbook = repo / "tofu/scratch/opnsense/acceptance/stray_rule.yaml"
        self.cert = out_dir / "first-boot" / "gateway-cert.pem"
        self.creds = out_dir / "credentials.tfvars"
        self.key = out_dir / "runner_key"

    # --- what a preflight of either backend asks
    def _image_problems(self) -> list[str]:
        return image_problems(self.image_url, self.image_checksum)

    def _out_dir_problems(self) -> list[str]:
        if self.out.resolve().is_relative_to(self.repo.resolve()):
            return [f"OUT_DIR holds credentials and must be outside the repository: {self.out}"]
        return []

    def _tool_problems(self, tools: Sequence[str]) -> list[str]:
        return [f"{tool} is not installed here" for tool in tools if shutil.which(tool) is None]

    def _collection_problems(self) -> list[str]:
        """The pinned `oxlorg.opnsense` release and `httpx` in Ansible's Python, which the play's modules need."""
        problems = []
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

    # --- Backend
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

    def stray(self, spec: Spec) -> tuple[int, str]:
        """Add a firewall rule the play does not write, on the interface the role's list gives the desktops zone."""
        zones = re.findall(
            r"^  - \{ name: desktops,.* interface: ([a-z0-9]+),", (self.repo / "ansible/roles/opnsense_gateway/defaults/main.yaml").read_text(), re.MULTILINE
        )
        if not zones:
            return 1, "the role's zone list has no desktops zone with an interface\n"
        extra = {"ca_file": str(self.cert), "api_port": int(self.local_port), "credentials": str(self.creds), "interface": zones[0]}
        return self.run([self.ansible, str(self.stray_playbook), "-e", json.dumps(extra)], env=self._noproxy_env(), cwd=self.repo, on_output=self.echo)

    def vlans(self, spec: Spec) -> tuple[int, str]:
        url = f"https://{MGMT_NAME}:{self.local_port}/{gateway_api.INTERFACE_LIST_PATH}"
        key, secret = self._credential("opnsense_api_key"), self._credential("opnsense_api_secret")
        if not (key and secret):
            return 1, f"no API credentials in {self.creds}\n"
        status, body = self.api_get(url, cafile=self.cert, key=key, secret=secret)
        passed, verdict = gateway_api.judge_vlans(status, body, spec.vlans)
        return (0 if passed else 1), f"GET /{gateway_api.INTERFACE_LIST_PATH} -> HTTP {status}\n{body.rstrip()}\n{verdict}\n"

    def logs(self) -> dict[str, str]:
        paths = [self.out / name for name in self.LOG_FILES]
        for name in self.LOG_DIRS:
            directory = self.out / name
            paths += sorted(directory.iterdir()) if directory.is_dir() else []
        found = {}
        for path in paths:
            if path.is_file():
                text = path.read_text(errors="replace")
                found[path.name if path.parent == self.out else f"{path.parent.name}-{path.name}"] = text[-LOG_LIMIT:]
        return found

    def secrets(self) -> list[str]:
        values = [*self.remembered, *(value for name in CREDENTIAL_NAMES if (value := self._credential(name)))]
        token = self.env.get("PROXMOX_API_TOKEN", "")
        if "=" in token:
            values.append(token.rsplit("=", 1)[1])
        self.remembered = list(dict.fromkeys(values))
        return self.remembered
