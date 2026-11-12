"""Tests for the namespace canaries a scratch gateway is checked with.

The first group runs anywhere. The second builds namespaces, a bridge and sshd daemons, and runs the real runner through
them against a stand-in gateway whose firewall the test changes: it needs root, `ip`, `nft`, `sshd` and `ssh-keygen`, and
is skipped where it has not got them (the CI runners run as an ordinary user).

Run via `uv run pytest tools/tests/ -v`; as root for the second group.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from network_checks import runner, scratch_canaries, scratch_plan
from network_checks.flow_list import load_flow_list
from stand_in_flows import FLOWS, VLANS

PACKAGE = Path(scratch_canaries.__file__).resolve()
BRIDGE = "opngbr"
GATEWAY_NS = "opng-gateway"


class TestHosts:
    def test_the_runner_comes_first_with_its_fixed_mac_and_each_zone_gets_a_distinct_one(self, flows_path):
        plan = scratch_plan.build_plan(load_flow_list(flows_path), VLANS)
        listed = scratch_canaries.hosts(plan)
        zone_macs = [scratch_canaries.macs(index, host["mac"])[1] for index, host in enumerate(listed)]

        assert [host["name"] for host in listed] == ["runner", *load_flow_list(flows_path).zones]
        assert zone_macs[0] == scratch_plan.RUNNER_MAC
        assert len(set(zone_macs)) == len(zone_macs)

    def test_a_zone_host_holds_its_canary_and_its_stand_ins(self, flows_path):
        plan = scratch_plan.build_plan(load_flow_list(flows_path), VLANS)

        assert {host["name"]: host["addresses"] for host in scratch_canaries.hosts(plan)}["services"] == ["192.168.20.8", "192.168.20.5"]

    def test_the_sshd_answers_on_the_canary_for_the_key_given_and_nothing_else(self, tmp_path):
        config = scratch_canaries.sshd_config(tmp_path, "services", "192.168.20.8")

        assert "ListenAddress 192.168.20.8\n" in config
        assert f"AuthorizedKeysFile {tmp_path}/authorized_keys\n" in config
        assert "PasswordAuthentication no\n" in config
        assert "PermitRootLogin prohibit-password\n" in config

    def test_the_module_is_written_for_the_python_a_node_has(self):
        """It runs under the node's own `python3`, older than the 3.14 the repo's formatter targets, which cannot read
        `except A, B:` without parentheses. A formatter that strips them must not reach this file."""
        assert re.search(r"^\s*except\s+[\w.]+\s*,", PACKAGE.read_text(), flags=re.MULTILINE) is None

    def test_the_module_imports_nothing_of_the_repository_so_it_can_be_copied_to_the_node(self):
        names = {line.split()[1].split(".")[0] for line in PACKAGE.read_text().splitlines() if line.startswith(("import ", "from "))}

        assert names <= set(sys.stdlib_module_names) | {"__future__"}


NEEDS = ("ip", "nft", "sshd", "ssh", "ssh-keygen")
can_build = os.geteuid() == 0 and all(shutil.which(tool) for tool in NEEDS)


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    root = tmp_path_factory.mktemp("lab")
    state = root / "state"
    key = root / "key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    flows = root / "flows.yaml"
    flows.write_text(yaml.safe_dump(FLOWS))
    plan = root / "plan.json"
    plan.write_text(json.dumps(scratch_plan.build_plan(load_flow_list(flows), VLANS)))
    scratch_canaries.teardown()
    subprocess.run(["ip", "link", "add", BRIDGE, "type", "bridge"], check=True)
    subprocess.run(["ip", "link", "set", BRIDGE, "up"], check=True)
    gateway()
    assert scratch_canaries.main(["x", "up", str(plan), BRIDGE, str(state), f"{key}.pub", "--no-vlan"]) == 0
    yield {"state": state, "key": key, "flows": flows}
    scratch_canaries.teardown()
    subprocess.run(["ip", "netns", "del", GATEWAY_NS], check=False)
    subprocess.run(["ip", "link", "del", "opngw"], check=False)
    subprocess.run(["ip", "link", "del", BRIDGE], check=False)


def gateway() -> None:
    """A router in its own namespace with an address in each zone, on the bridge, forwarding only what a rule allows."""
    run = subprocess.run
    run(["ip", "netns", "add", GATEWAY_NS], check=True)
    run(["ip", "link", "add", "opngw", "type", "veth", "peer", "name", "opngwp"], check=True)
    run(["ip", "link", "set", "opngwp", "netns", GATEWAY_NS], check=True)
    run(["ip", "link", "set", "opngw", "master", BRIDGE], check=True)
    run(["ip", "link", "set", "opngw", "up"], check=True)
    for command in (
        ["ip", "link", "set", "lo", "up"],
        ["ip", "link", "set", "opngwp", "up"],
        ["ip", "addr", "add", "192.168.20.1/24", "dev", "opngwp"],
        ["ip", "addr", "add", "192.168.40.1/24", "dev", "opngwp"],
        ["sysctl", "-q", "-w", "net.ipv4.ip_forward=1"],
        ["sysctl", "-q", "-w", "net.ipv4.conf.all.send_redirects=0"],
        ["sysctl", "-q", "-w", "net.ipv4.conf.opngwp.send_redirects=0"],
    ):
        run(["ip", "netns", "exec", GATEWAY_NS, *command], check=True)


def rules(allowed: list[str]) -> None:
    text = "flush ruleset\ntable ip filter {\n chain forward {\n  type filter hook forward priority 0; policy drop;\n  ct state established,related accept\n"
    text += "".join(f"  {rule} accept\n" for rule in allowed) + " }\n}\n"
    subprocess.run(["ip", "netns", "exec", GATEWAY_NS, "nft", "-f", "-"], input=text, text=True, check=True)


@pytest.mark.skipif(not can_build, reason="builds namespaces and daemons: needs root, ip, nft, sshd, ssh and ssh-keygen")
class TestAgainstAStandInGateway:
    """The runner through the relay to canaries behind a router whose forward rules the test changes."""

    RUNNER_TO_SERVICES = "ip saddr 192.168.40.250 ip daddr 192.168.20.8 tcp dport 22"
    DESKTOPS_TO_VAULT = "ip saddr 192.168.40.8 ip daddr 192.168.20.5 tcp dport 8200"

    def run_runner(self, lab, capsys, *extra: str) -> tuple[int, str]:
        proxy = f"{sys.executable} {PACKAGE} relay {lab['state']} %h %p"
        ssh = f"ssh -i {lab['key']} -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o 'ProxyCommand={proxy}'"
        code = runner.main(["--ssh-user", "root", "--ssh-command", ssh, "--flows", str(lab["flows"]), *extra])
        return code, capsys.readouterr().out

    def test_every_flow_passes_when_the_gateway_forwards_what_the_flows_allow(self, lab, capsys):
        rules([self.RUNNER_TO_SERVICES, self.DESKTOPS_TO_VAULT])

        code, out = self.run_runner(lab, capsys)

        assert code == 0, out
        assert out.count("PASS ") == 5

    def test_removing_the_rule_an_allow_flow_depends_on_makes_its_probe_fail(self, lab, capsys):
        rules([self.RUNNER_TO_SERVICES])

        code, out = self.run_runner(lab, capsys, "--flow", "desktops-vault-allowed")

        assert code == 1
        assert out.startswith("FAIL desktops-vault-allowed")

    def test_the_probe_passes_again_when_the_rule_is_put_back(self, lab, capsys):
        rules([self.RUNNER_TO_SERVICES, self.DESKTOPS_TO_VAULT])

        code, out = self.run_runner(lab, capsys, "--flow", "desktops-vault-allowed")

        assert code == 0, out

    def test_a_deny_fails_when_the_gateway_lets_the_attempt_through(self, lab, capsys):
        rules([self.RUNNER_TO_SERVICES, "ip saddr 192.168.40.8 ip daddr 192.168.20.8 tcp dport 22"])

        code, out = self.run_runner(lab, capsys, "--flow", "desktops-to-services-canary-denied")

        assert code == 1
        assert "FAIL desktops-to-services-canary-denied" in out

    def test_a_canary_the_runner_cannot_reach_fails_every_flow_from_its_zone(self, lab, capsys):
        rules([])

        code, out = self.run_runner(lab, capsys, "--flow", "services-canary-ssh")

        assert code == 1
        assert out.startswith("FAIL services-canary-ssh")

    def test_down_removes_every_namespace_and_link(self, lab):
        scratch_canaries.teardown()

        listing = subprocess.run(["ip", "netns", "list"], capture_output=True, text=True, check=True).stdout
        links = subprocess.run(["ip", "-o", "link", "show"], capture_output=True, text=True, check=True).stdout

        assert scratch_canaries.NS_PREFIX + "runner" not in listing
        assert f" {scratch_canaries.LINK_PREFIX}0" not in links
