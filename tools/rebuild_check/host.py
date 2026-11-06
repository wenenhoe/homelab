#!/usr/bin/env python3
"""Check a rebuilt host over SSH and say what is wrong, one line per check.

`docker ps` reporting every container healthy does not prove the host works:
tinyauth and lldap were both healthy while tinyauth could not reach lldap,
because the host's own name resolved to loopback inside a container. These
checks look at what a rebuild is known to get wrong: the address came from
DHCP, the dracut network file is back, a container resolves the host's name to
something else, the timezone is wrong, a unit failed, a container is not
running. A host without Docker skips the two that need it. `security` has a few
more, for what only it runs, and `tailscale` checks that it forwards packets.

Each check is a command run on the host and a judgement on its output; none
changes anything. The expected address is what the lab's DNS says for the
host's name, so a stale or wrong record shows up as a failed check on the host
rather than being trusted.

Usage:
    cd tools && python3 -m rebuild_check.host <host>

Exits 1 when any check fails.
"""

from __future__ import annotations

import re
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import yaml
from utils.repo import INVENTORY_PATH, PROJECT_ROOT, connect_ssh, main_domain, ssh_target

# Per command, not for the run: `docker run` pulls nothing but can still take a moment.
COMMAND_TIMEOUT_SECONDS = 60

# The image the compose role seeds volumes with, so every host has it already.
SEED_TASKS = PROJECT_ROOT / "ansible/roles/compose/tasks/seed_volume.yaml"
GROUP_VARS = PROJECT_ROOT / "ansible/inventory/group_vars/all/main.yaml"

# What a healthy container looks like next to the others: openbao reports
# unhealthy whenever it is sealed, which is its own check below.
SEALED_MEANS_UNHEALTHY = {"openbao"}


class Result(NamedTuple):
    ok: bool
    detail: str


class Check(NamedTuple):
    name: str
    ok: bool
    detail: str


Runner = Callable[[str], tuple[int, str]]


@dataclass(frozen=True)
class Expected:
    host: str
    address: str
    fqdn: str
    timezone: str
    probe_image: str
    runs_docker: bool = True


def _first_address(output: str) -> str:
    fields = output.split()
    return fields[0] if fields else ""


def address_is_static(run: Runner, expected: Expected) -> Result:
    status, out = run("ip -4 -o addr show scope global")
    lines = [line for line in out.splitlines() if f"{expected.address}/" in line]
    if status != 0 or not lines:
        return Result(False, f"no global address {expected.address} (got: {out.strip() or 'nothing'})")
    if "dynamic" in lines[0]:
        return Result(False, f"{expected.address} is a DHCP lease, not the static address")
    return Result(True, f"{expected.address} is static")


def no_dracut_network_file(run: Runner, expected: Expected) -> Result:
    status, out = run("ls /run/systemd/network")
    if status == 0 and "zzzz-dracut-default.network" in out.split():
        return Result(False, "/run/systemd/network/zzzz-dracut-default.network is present: the initramfs brought the NIC up with DHCP")
    return Result(True, "no dracut network file")


def own_name_resolves_to_its_address(run: Runner, expected: Expected) -> Result:
    status, out = run(f"getent hosts {expected.fqdn}")
    got = _first_address(out)
    if status != 0 or got != expected.address:
        return Result(False, f"{expected.fqdn} resolves to {got or 'nothing'} on the host, not {expected.address}")
    return Result(True, f"{expected.fqdn} is {got}")


def containers_resolve_the_hosts_name(run: Runner, expected: Expected) -> Result:
    status, out = run(f"docker run --rm --network caddy-proxy {expected.probe_image} getent hosts {expected.fqdn}")
    got = _first_address(out)
    if status != 0 or got != expected.address:
        return Result(False, f"a container on caddy-proxy resolves {expected.fqdn} to {got or 'nothing'}, not {expected.address}")
    return Result(True, f"a container on caddy-proxy resolves {expected.fqdn} to {got}")


def timezone_is_the_inventorys(run: Runner, expected: Expected) -> Result:
    status, out = run("timedatectl show --property=Timezone --value")
    got = out.strip()
    if status != 0 or got != expected.timezone:
        return Result(False, f"timezone is {got or 'unknown'}, not {expected.timezone}")
    return Result(True, f"timezone is {got}")


def no_failed_units(run: Runner, expected: Expected) -> Result:
    status, out = run("systemctl --failed --no-legend --plain")
    failed = [line.split()[0] for line in out.splitlines() if line.strip()]
    if status != 0 or failed:
        return Result(False, f"failed units: {', '.join(failed) or 'systemctl failed'}")
    return Result(True, "no failed units")


def containers_are_running_and_healthy(run: Runner, expected: Expected) -> Result:
    status, out = run("docker ps -a --format '{{.Names}}|{{.State}}|{{.Status}}'")
    if status != 0:
        return Result(False, "docker ps failed")
    bad = []
    for line in out.splitlines():
        name, _, rest = line.partition("|")
        state, _, detail = rest.partition("|")
        if name in SEALED_MEANS_UNHEALTHY:
            continue
        if state != "running" or "(unhealthy)" in detail or "health: starting" in detail:
            bad.append(f"{name} ({state}{', ' + detail if detail else ''})")
    if bad:
        return Result(False, "not settled: " + "; ".join(bad))
    return Result(True, "every container is running and healthy")


def openbao_is_unsealed(run: Runner, expected: Expected) -> Result:
    status, out = run("docker exec openbao bao status -address=https://127.0.0.1:8200")
    if status == 0:
        return Result(True, "unsealed")
    if status == 2:
        return Result(False, "sealed or uninitialised: unseal it with the original shares")
    return Result(False, f"bao status failed ({status}): {out.strip()[:120]}")


def step_ca_is_healthy(run: Runner, expected: Expected) -> Result:
    status, out = run("docker exec step-ca step ca health")
    if status == 0 and out.strip() == "ok":
        return Result(True, "ok")
    return Result(False, f"step ca health said {out.strip()[:120] or 'nothing'} (exit {status})")


def r2_read_watcher_is_running(run: Runner, expected: Expected) -> Result:
    status, out = run("systemctl is-active r2-read-watcher.service r2-read-watcher-heartbeat.timer")
    states = out.split()
    if status == 0 and states == ["active", "active"]:
        return Result(True, "the service and its heartbeat timer are active")
    return Result(False, f"r2-read-watcher is {' / '.join(states) or 'not installed'}: it is installed by hand, see openbao-r2-read-watcher.md")


def tinyauth_reaches_ldap(run: Runner, expected: Expected) -> Result:
    status, out = run("docker logs --since 10m tinyauth 2>&1 | grep -ciE 'ldap.*(error|failed)' || true")
    count = out.strip()
    if status != 0 or count != "0":
        return Result(False, f"{count or '?'} LDAP error line(s) in tinyauth's last 10 minutes of log")
    return Result(True, "no LDAP errors in tinyauth's last 10 minutes of log")


def ip_forwarding_is_on(run: Runner, expected: Expected) -> Result:
    status, out = run("sysctl -n net.ipv4.ip_forward net.ipv6.conf.all.forwarding")
    values = out.split()
    if status != 0 or values != ["1", "1"]:
        got = " and ".join(values) or "unknown"
        return Result(False, f"net.ipv4.ip_forward and net.ipv6.conf.all.forwarding are {got}, not 1 and 1: the router drops what it should forward")
    return Result(True, "IPv4 and IPv6 forwarding are on")


COMMON_CHECKS = (
    address_is_static,
    no_dracut_network_file,
    own_name_resolves_to_its_address,
    containers_resolve_the_hosts_name,
    timezone_is_the_inventorys,
    no_failed_units,
    containers_are_running_and_healthy,
)

# The checks that run a docker command, which a host without Docker cannot answer.
DOCKER_CHECKS = (containers_resolve_the_hosts_name, containers_are_running_and_healthy)

HOST_CHECKS = {
    "security": (openbao_is_unsealed, step_ca_is_healthy, tinyauth_reaches_ldap, r2_read_watcher_is_running),
    "tailscale": (ip_forwarding_is_on,),
}


def run_checks(run: Runner, expected: Expected) -> list[Check]:
    checks = []
    common = [check for check in COMMON_CHECKS if expected.runs_docker or check not in DOCKER_CHECKS]
    for check in (*common, *HOST_CHECKS.get(expected.host, ())):
        result = check(run, expected)
        checks.append(Check(check.__name__, result.ok, result.detail))
    return checks


def ssh_runner(client) -> Runner:
    def run(command: str) -> tuple[int, str]:
        _stdin, stdout, _stderr = client.exec_command(command, timeout=COMMAND_TIMEOUT_SECONDS)
        return stdout.channel.recv_exit_status(), stdout.read().decode(errors="replace")

    return run


def seed_image(tasks: Path = SEED_TASKS) -> str:
    match = re.search(r"image:\s*(alpine:\S+@sha256:[0-9a-f]{64})", tasks.read_text())
    if match is None:
        raise SystemExit(f"no alpine image with a digest in {tasks}")
    return match.group(1)


def runs_docker(host: str, inventory_path: Path = INVENTORY_PATH) -> bool:
    """False for a host of the `network_infra` group, which has no Docker."""
    group = yaml.safe_load(inventory_path.read_text())["all"]["children"].get("network_infra") or {}
    return host not in (group.get("hosts") or {})


def expected_for(host: str, resolve: Callable[[str], str] = socket.gethostbyname) -> Expected:
    fqdn = f"{host}.internal.{main_domain()}"
    try:
        address = resolve(fqdn)
    except OSError as exc:
        raise SystemExit(f"{fqdn} does not resolve from here ({exc}): the lab's DNS has no address to hold the host to") from exc
    timezone = yaml.safe_load(GROUP_VARS.read_text())["server_timezone"]
    return Expected(host=host, address=address, fqdn=fqdn, timezone=timezone, probe_image=seed_image(), runs_docker=runs_docker(host))


def report(checks: list[Check]) -> int:
    width = max(len(check.name) for check in checks)
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'}  {check.name.ljust(width)}  {check.detail}")
    failed = [check.name for check in checks if not check.ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python3 -m rebuild_check.host <host>", file=sys.stderr)
        return 2
    host = args[0]
    user, address, key_path = ssh_target(host)
    expected = expected_for(host)
    client = connect_ssh(user, address, key_path)
    try:
        checks = run_checks(ssh_runner(client), expected)
    finally:
        client.close()
    return report(checks)


if __name__ == "__main__":
    raise SystemExit(main())
