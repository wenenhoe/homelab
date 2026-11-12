#!/usr/bin/env python3
"""Canaries as network namespaces on the Proxmox node, for running the boundary checks against a scratch gateway.

Run as root on the node, with the scratch gateway up on its isolated bridge. The module uses the standard library only, so
it can be copied to the node on its own. `scratch_plan` writes the plan it reads.

    scratch_canaries.py up PLAN.json BRIDGE STATE_DIR AUTHORIZED_KEY.pub [--no-vlan]
    scratch_canaries.py down
    scratch_canaries.py relay STATE_DIR HOST PORT

`up` makes one namespace per zone, joined to the bridge by a veth pair with the zone's VLAN tag, a default route through
the gateway's address in the zone and a fixed MAC. The zone's canary address answers SSH on 22 for the key given, so the
runner's session reaches it as it would a canary VM. Each stand-in host of the plan accepts and closes TCP connections.
One more namespace holds the runner's host, at the address the gateway's play admits as an operator host.

The runner itself stays where the repository is. Its SSH sessions leave through `relay` as a ProxyCommand, which opens the
connection from the runner's namespace, so the gateway sees the operator host's address as the source:

    ssh-command: ssh -i KEY -o ProxyCommand="ssh root@NODE python3 /path/scratch_canaries.py relay STATE_DIR %h %p"

`down` removes every namespace, link and process `up` made, including those a failed `up` left. The namespaces get fixed MACs,
so a gateway that kept an ARP entry from an earlier build still reaches the host.

--no-vlan puts the addresses on the veth itself, for the offline test only: the sandbox it runs in has no 802.1q.
"""

from __future__ import annotations

import json
import os
import selectors
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

NS_PREFIX = "opnc-"
LINK_PREFIX = "opc"
RUNNER = "runner"
READY_SECONDS = 15.0
SSHD_FILES = ("host_key", "authorized_keys")


def ns_name(name: str) -> str:
    return NS_PREFIX + name


def hosts(plan: dict) -> list[dict]:
    """The runner's host first, then each zone's: what gets a namespace."""
    runner = plan["runner"]
    return [{"name": RUNNER, "vlan": runner["vlan"], "gateway": runner["gateway"], "mac": runner["mac"], "addresses": [runner["address"]]}] + [
        {
            "name": zone["name"],
            "vlan": zone["vlan"],
            "gateway": zone["gateway"],
            "mac": None,
            "addresses": [zone["canary"]] + [item["address"] for item in zone["listeners"]],
        }
        for zone in plan["zones"]
    ]


def link_name(index: int) -> str:
    return f"{LINK_PREFIX}{index}"


def macs(index: int, fixed: str | None) -> tuple[str, str]:
    """The MACs of a host's two veth ends: the host side and the namespace side."""
    return f"02:00:00:00:{index:02x}:01", fixed or f"02:00:00:00:{index:02x}:02"


def sshd_config(state: Path, name: str, canary: str) -> str:
    """The sshd that answers on a canary's address: the key given, no password, nothing of the node's own."""
    lines = [
        "Port 22",
        f"ListenAddress {canary}",
        f"HostKey {state}/host_key",
        f"AuthorizedKeysFile {state}/authorized_keys",
        f"PidFile {state}/sshd-{name}.pid",
        "PermitRootLogin prohibit-password",
        "PasswordAuthentication no",
        "KbdInteractiveAuthentication no",
        "UsePAM no",
        "StrictModes no",
        "LogLevel ERROR",
    ]
    return "\n".join(lines) + "\n"


def run(*args: str, ns: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["ip", "netns", "exec", ns, *args] if ns else list(args)
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if check and done.returncode != 0:
        raise SystemExit(f"{' '.join(cmd)} failed: {done.stderr.strip() or done.stdout.strip()}")
    return done


def filtering(bridge: str) -> bool:
    try:
        return Path(f"/sys/class/net/{bridge}/bridge/vlan_filtering").read_text().strip() == "1"
    except OSError:
        return False


def teardown() -> None:
    """Remove every namespace, link and process `up` made."""
    listing = run("ip", "netns", "list", check=False).stdout.split("\n")
    for line in listing:
        name = line.split(" ")[0]
        if not name.startswith(NS_PREFIX):
            continue
        for pid in run("ip", "netns", "pids", name, check=False).stdout.split():
            run("kill", pid, check=False)
        run("ip", "netns", "del", name, check=False)
    links = run("ip", "-o", "link", "show", check=False).stdout.split("\n")
    for line in links:
        fields = line.split(": ")
        if len(fields) > 1 and fields[1].split("@")[0].startswith(LINK_PREFIX):
            run("ip", "link", "del", fields[1].split("@")[0], check=False)


def build(plan: dict, bridge: str, vlan: bool) -> None:
    tagged = vlan and filtering(bridge)
    for index, host in enumerate(hosts(plan)):
        ns, link = ns_name(host["name"]), link_name(index)
        peer = link + "p"
        host_mac, peer_mac = macs(index, host["mac"])
        run("ip", "netns", "add", ns)
        run("ip", "link", "add", link, "address", host_mac, "type", "veth", "peer", "name", peer, "address", peer_mac)
        run("ip", "link", "set", peer, "netns", ns)
        run("ip", "link", "set", link, "master", bridge)
        run("ip", "link", "set", link, "up")
        if tagged:
            run("bridge", "vlan", "add", "dev", link, "vid", str(host["vlan"]))
        run("ip", "link", "set", "lo", "up", ns=ns)
        for scope in ("all", "default"):
            run("sysctl", "-q", "-w", f"net.ipv4.conf.{scope}.accept_redirects=0", ns=ns)
        run("ip", "link", "set", peer, "up", ns=ns)
        run("sysctl", "-q", "-w", f"net.ipv4.conf.{peer}.accept_redirects=0", ns=ns)
        device = peer
        if vlan:
            device = f"{peer}.{host['vlan']}"
            run("ip", "link", "add", "link", peer, "name", device, "type", "vlan", "id", str(host["vlan"]), ns=ns)
            run("ip", "link", "set", device, "up", ns=ns)
            run("sysctl", "-q", "-w", f"net.ipv4.conf.{device}.accept_redirects=0", ns=ns)
        for address in host["addresses"]:
            run("ip", "addr", "add", f"{address}/24", "dev", device, ns=ns)
        run("ip", "route", "add", "default", "via", host["gateway"], ns=ns)


def start(state: Path, plan: dict) -> list[subprocess.Popen]:
    """The sshd on each canary and the listener of each stand-in host, each inside its zone's namespace."""
    procs = []
    sshd = shutil.which("sshd") or "/usr/sbin/sshd"
    Path("/run/sshd").mkdir(parents=True, exist_ok=True)
    for zone in plan["zones"]:
        config = state / f"sshd-{zone['name']}.conf"
        config.write_text(sshd_config(state, zone["name"], zone["canary"]))
        procs.append(
            subprocess.Popen(
                ["ip", "netns", "exec", ns_name(zone["name"]), sshd, "-D", "-e", "-f", str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        )
        for item in zone["listeners"]:
            command = ["ip", "netns", "exec", ns_name(zone["name"]), sys.executable, str(Path(__file__).resolve()), "serve", item["address"], str(item["port"])]
            procs.append(subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    return procs


def listening(zone: str, address: str, port: int) -> bool:
    code = f"import socket; socket.create_connection(({address!r}, {port}), 2).close()"
    return run(sys.executable, "-c", code, ns=ns_name(zone), check=False).returncode == 0


def wait_ready(plan: dict) -> None:
    """Every canary and stand-in host answers inside its own namespace, so a timeout later is a block and not a dead host."""
    pending = [(zone["name"], zone["canary"], 22) for zone in plan["zones"]]
    pending += [(zone["name"], item["address"], item["port"]) for zone in plan["zones"] for item in zone["listeners"]]
    deadline = time.monotonic() + READY_SECONDS
    while pending and time.monotonic() < deadline:
        pending = [item for item in pending if not listening(*item)]
        if pending:
            time.sleep(0.3)
    if pending:
        raise SystemExit(f"nothing answers inside its own zone: {pending}")


def up(plan_path: str, bridge: str, state_dir: str, key_path: str, vlan: bool) -> int:
    teardown()
    plan = json.loads(Path(plan_path).read_text())
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    (state / "authorized_keys").write_text(Path(key_path).read_text())
    host_key = state / "host_key"
    host_key.unlink(missing_ok=True)
    run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host_key))
    try:
        build(plan, bridge, vlan)
        procs = start(state, plan)
        (state / "pids").write_text("\n".join(str(proc.pid) for proc in procs) + "\n")
        wait_ready(plan)
    except BaseException:
        teardown()
        raise
    (state / "runner").write_text(ns_name(RUNNER))
    print(f"ready: {len(plan['zones'])} canaries, runner at {plan['runner']['address']}")
    return 0


def serve(address: str, port: int) -> int:
    """Accept TCP connections on the address and close them: a stand-in for a service the flow list reaches."""
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((address, port))
        server.listen(16)
        while True:
            connection, _ = server.accept()
            connection.close()


def relay(state_dir: str, host: str, port: str) -> int:
    """Open a TCP connection from the runner's namespace and carry it over stdin and stdout, as a ProxyCommand."""
    namespace = (Path(state_dir) / "runner").read_text().strip()
    os.execvp("ip", ["ip", "netns", "exec", namespace, sys.executable, str(Path(__file__).resolve()), "pump", host, port])  # noqa: S606 - this module's own pump, in the runner's namespace


def pump(host: str, port: int) -> int:
    connection = socket.create_connection((host, port), 10)
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin.fileno(), selectors.EVENT_READ, "in")
    selector.register(connection, selectors.EVENT_READ, "out")
    while True:
        for key, _ in selector.select():
            if key.data == "in":
                data = os.read(sys.stdin.fileno(), 65536)
                if not data:
                    return 0
                connection.sendall(data)
            else:
                data = connection.recv(65536)
                if not data:
                    return 0
                os.write(sys.stdout.fileno(), data)


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command == "serve" and len(argv) == 4:
        return serve(argv[2], int(argv[3]))
    if command == "pump" and len(argv) == 4:
        return pump(argv[2], int(argv[3]))
    if command == "relay" and len(argv) == 5:
        return relay(argv[2], argv[3], argv[4])
    if os.geteuid() != 0:
        print("run as root")
        return 2
    if command == "down" and len(argv) == 2:
        teardown()
        return 0
    flags = [arg for arg in argv[2:] if arg != "--no-vlan"]
    if command == "up" and len(flags) == 4:
        return up(flags[0], flags[1], flags[2], flags[3], "--no-vlan" not in argv)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
