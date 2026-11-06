#!/usr/bin/env python3
"""Ask both of the lab's DNS servers the same questions and say where they differ.

`services` (primary) and `storage` (secondary) each answer for the host and lan zones, and the gateway
forwards to both. When one of them is rebuilt, it can come back holding an older zone or none of the new
records, and a resolver that happens to ask it gets a stale answer while the other looks fine. These checks
query each server directly: the zones' SOA serials agree, every managed host's name resolves to the same
address on both, and for a host Tofu built that address is the one in the generated inventory.

Usage:
    cd tools && python3 -m rebuild_check.dns [host ...]

With no host, every host in inventory.yaml's managed_hosts and network_infra is checked. Needs `dig` on the
machine it runs on, and changes nothing. Exits 1 when any check fails.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

import yaml
from utils.repo import GENERATED_INVENTORY_PATH, INVENTORY_PATH, PROJECT_ROOT, main_domain

from rebuild_check.host import Check, Result, report

GROUP_VARS = PROJECT_ROOT / "ansible/inventory/group_vars/all/main.yaml"
DIG_TIMEOUT_SECONDS = 3

# `dig +short @SERVER NAME TYPE` as (exit status, output). An unreachable server is a non-zero status.
Dig = Callable[[str, str, str], tuple[int, str]]


@dataclass(frozen=True)
class Servers:
    primary: str
    secondary: str

    def both(self) -> tuple[tuple[str, str], tuple[str, str]]:
        return (("primary", self.primary), ("secondary", self.secondary))


@dataclass(frozen=True)
class Plan:
    servers: Servers
    zones: tuple[str, ...]
    names: dict[str, str | None]  # name to the address it must have, or None to require only that the servers agree


def dig_runner(server: str, name: str, record_type: str) -> tuple[int, str]:
    result = subprocess.run(
        ["dig", "+short", f"+time={DIG_TIMEOUT_SECONDS}", "+tries=1", f"@{server}", name, record_type],
        capture_output=True,
        text=True,
        timeout=DIG_TIMEOUT_SECONDS * 2 + 2,
        check=False,
    )
    return result.returncode, result.stdout


def soa_serial(dig: Dig, server: str, zone: str) -> tuple[str | None, str]:
    """(serial, why not): the zone's SOA serial on `server`, or None and what went wrong."""
    status, out = dig(server, zone, "SOA")
    if status != 0:
        return None, f"{server} did not answer (dig exit {status})"
    fields = out.split()
    if len(fields) < 7 or not fields[2].isdigit():
        return None, f"{server} has no SOA for {zone}"
    return fields[2], ""


def addresses(dig: Dig, server: str, name: str) -> tuple[frozenset[str] | None, str]:
    """The addresses `name` resolves to on `server`, following a CNAME; None and why when it did not answer."""
    status, out = dig(server, name, "A")
    if status != 0:
        return None, f"{server} did not answer (dig exit {status})"
    found = frozenset(line for line in out.split() if line.replace(".", "").isdigit())
    if not found:
        return None, f"{server} has no address for {name}"
    return found, ""


def zones_have_one_serial(dig: Dig, plan: Plan) -> Result:
    problems = []
    for zone in plan.zones:
        serials = {}
        for role, server in plan.servers.both():
            serial, why = soa_serial(dig, server, zone)
            if serial is None:
                problems.append(f"{zone}: {why}")
            else:
                serials[role] = serial
        if len(set(serials.values())) > 1:
            problems.append(f"{zone}: serial {serials['primary']} on the primary, {serials['secondary']} on the secondary: the transfer has not happened")
    if problems:
        return Result(False, "; ".join(problems))
    return Result(True, f"the primary and secondary hold the same serial of {', '.join(plan.zones)}")


def name_resolves_alike(dig: Dig, plan: Plan, name: str) -> Result:
    expected = plan.names[name]
    answers = {}
    for role, server in plan.servers.both():
        found, why = addresses(dig, server, name)
        if found is None:
            return Result(False, why)
        answers[role] = found
    if answers["primary"] != answers["secondary"]:
        return Result(False, f"the primary says {sorted(answers['primary'])}, the secondary {sorted(answers['secondary'])}")
    if expected is not None and answers["primary"] != {expected}:
        return Result(False, f"both say {sorted(answers['primary'])}, the inventory says {expected}")
    return Result(True, ", ".join(sorted(answers["primary"])) + (" as the inventory says" if expected else ""))


def run_checks(dig: Dig, plan: Plan) -> list[Check]:
    first = zones_have_one_serial(dig, plan)
    checks = [Check("zones_have_one_serial", first.ok, first.detail)]
    for name in plan.names:
        result = name_resolves_alike(dig, plan, name)
        checks.append(Check(f"resolves_alike: {name}", result.ok, result.detail))
    return checks


def plan_for(hosts: list[str]) -> Plan:
    domain = main_domain()
    host_domain = f"internal.{domain}"
    lan_domain = f"lan.{domain}"
    group_vars = yaml.safe_load(GROUP_VARS.read_text())
    inventory = yaml.safe_load(INVENTORY_PATH.read_text())["all"]["children"]
    known = [name for group in ("managed_hosts", "network_infra") for name in (inventory.get(group) or {}).get("hosts") or {}]
    generated = {}
    if GENERATED_INVENTORY_PATH.exists():
        generated = (yaml.safe_load(GENERATED_INVENTORY_PATH.read_text()) or {}).get("all", {}).get("hosts", {})
    unknown = sorted(set(hosts) - set(known))
    if unknown:
        raise SystemExit(f"unknown host(s) {', '.join(unknown)}; the inventory has: {', '.join(known)}")
    names: dict[str, str | None] = {}
    for host in hosts or known:
        names[f"{host}.{host_domain}"] = generated.get(host, {}).get("ansible_host")
    names[f"s3.store.{lan_domain}"] = None
    servers = Servers(group_vars["dns_primary_address"], group_vars["dns_secondary_address"])
    return Plan(servers=servers, zones=(host_domain, lan_domain), names=names)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if any(arg.startswith("-") for arg in args):
        print("usage: python3 -m rebuild_check.dns [host ...]", file=sys.stderr)
        return 2
    return report(run_checks(dig_runner, plan_for(args)))


if __name__ == "__main__":
    raise SystemExit(main())
