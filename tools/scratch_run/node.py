"""The backend that runs the gateway on the Proxmox node, through the repo's own scripts.

It does what an operator does by hand today ([`opnsense-scratch-gateway.md`], [`network-boundary-checks.md`]):
`scratch_gateway.sh up` builds the gateway, the play and the block-rule playbook run from this machine through the
ssh forward, the namespace canaries go up on the node on first use, and the runner reaches them through a
ProxyCommand. `down` removes the canaries and then the gateway. Every command goes through one `Runner`, so the
tests see the argument lists and need no node.
"""

from __future__ import annotations

import json
import shlex
import shutil
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from network_checks.flow_list import load_flow_list
from network_checks.scratch_plan import build_plan, zone_vlans

from scratch_run import canary_vm, gateway_api
from scratch_run.gateway_steps import (
    MGMT_NAME,
    REPO,
    ApiGet,
    Echo,
    GatewaySteps,
    Runner,
    print_indented,
    resolve_host,
    run_command,
)
from scratch_run.spec import Spec

REMOTE_DIR = "/root/scratch-run"  # on the node: the canaries' plan, key and namespaces' state
DEFAULT_TEMPLATE_VM_ID = "106"  # `tofu/scratch/ubuntu`'s template_vm_id default: the Ubuntu template the VM is cloned from
VM_WAIT_SECONDS = 600  # a cloned VM boots and runs cloud-init before it answers over ssh
VM_POLL_SECONDS = 10


class NodeBackend(GatewaySteps):
    # What the gateway's build leaves in the state directory that the results keep (names relative to it; a directory is read file by file).
    LOG_FILES = ("build-seed.txt", "init.txt", "apply.txt")
    LOG_DIRS = ("update",)

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
        super().__init__(out_dir, image_url, image_checksum, env, runner, resolver, repo, echo, api_get, sleep, clock)
        self.node = env.get("NODE", "")
        self.lan_bridge = env.get("LAN_BRIDGE", "vmbr9")
        self.vmid = env.get("VM_ID", "501")
        self.gateway_script = repo / "tofu/scratch/opnsense/scratch_gateway.sh"
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

    # --- Backend
    def preflight(self, spec: Spec) -> list[str]:
        problems: list[str] = []
        for name in ("NODE", "PROXMOX_ENDPOINT", "PROXMOX_API_TOKEN"):
            if not self.env.get(name):
                problems.append(f"{name} is not set")
        problems += self._image_problems()
        problems += self._out_dir_problems()
        problems += self._tool_problems(("ssh", "scp", "ssh-keygen", self.ansible, "ansible-galaxy", *((self.tofu,) if spec.canary_vm else ())))
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
        problems += self._collection_problems()
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
