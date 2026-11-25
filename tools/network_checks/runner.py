#!/usr/bin/env python3
"""Tries the flows of the flow list from the canaries and decides the outcome (ADR 0094).

For each source zone in the selection the runner opens one SSH session to the zone's canary, sends the probe
module (probe.py) on the standard input of the canary's `python3` with the flows to try, and reads one JSON result
per flow back. Nothing is installed on the canary and it holds no credential or flow list.

An allow flow passes when its attempt succeeded. A deny flow passes only when the attempt failed and its control
passed in the same run, since the destination or the canary may simply be down; the control of each selected deny
is added to the run. `--without-canary` leaves out the flows that need a zone's canary, for a gateway on which that
zone has none, and the run says how many it left out. A probe the runner could not run, a session that failed and a flow with no result all count
as failed, and the exit status is zero only if every flow in the run passed.

Usage (from tools/): python -m network_checks.runner --ssh-user USER [--ssh-user-for ZONE=USER] [--tag TAG] [--flow ID]
    [--without-canary ZONE] [--ssh-command CMD]
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from network_checks import probe, rules
from network_checks.flow_list import FLOWS_PATH, Flow, FlowList, FlowListError, load_flow_list

DEFAULT_SSH_COMMAND = "ssh -o BatchMode=yes"
PROBE_TIMEOUT = 3.0
SESSION_MARGIN = 30.0  # seconds a session may take beyond its probes' own timeouts


class SessionError(Exception):
    """A session to a canary failed, or answered with something the runner cannot read."""


@dataclass(frozen=True)
class Outcome:
    flow_id: str
    passed: bool
    message: str


def need_canary(flow_list: FlowList, zones: Collection[str]) -> set[str]:
    """The ids of the flows that cannot be shown without the canary of one of `zones`: those tried from it, those aimed
    at its address, and the denies whose control is one of these."""
    addresses = {flow_list.zones[zone].canary for zone in zones}
    direct = {flow.id for flow in flow_list.flows if flow.source in zones or flow.destination.ip() in addresses}
    return direct | {flow.id for flow in flow_list.flows if flow.control in direct}


def select(flow_list: FlowList, tags: list[str], ids: list[str], without_canary: Collection[str] = ()) -> list[Flow]:
    """The flows to run: those with one of `tags` and those named in `ids`, or all when neither is given, less those that
    need the canary of a zone in `without_canary`, then the control of each selected deny, in the order of the flow list."""
    unknown = [flow_id for flow_id in ids if flow_id not in {flow.id for flow in flow_list.flows}]
    if unknown:
        raise ValueError(f"no flow has the id {', '.join(unknown)}")
    left_out = need_canary(flow_list, without_canary)
    contradicted = [flow_id for flow_id in ids if flow_id in left_out]
    if contradicted:
        raise ValueError(f"{', '.join(contradicted)} needs a canary that --without-canary leaves out")
    chosen = {flow.id for flow in flow_list.flows if (not tags and not ids) or flow.id in ids or set(tags) & set(flow.tags)} - left_out
    chosen |= {flow.control for flow in flow_list.flows if flow.id in chosen and flow.control}
    return [flow for flow in flow_list.flows if flow.id in chosen]


def _spec(flow: Flow, timeout: float) -> dict[str, object]:
    destination = flow.destination
    return {
        "id": flow.id,
        "kind": flow.kind,
        "address": destination.address,
        "port": destination.port,
        "protocol": destination.protocol,
        "query": flow.query,
        "timeout": timeout,
    }


def run_session(canary: str, user: str, ssh_command: list[str], python: str, specs: list[dict[str, object]], timeout: float) -> dict[str, dict[str, str]]:
    """The results of `specs` tried from the canary, by flow id. Raises SessionError when no result can be read."""
    remote = f"{shlex.quote(python)} - {shlex.quote(json.dumps(specs))}"
    argv = [*ssh_command, f"{user}@{canary}", remote]
    try:
        done = subprocess.run(argv, input=Path(probe.__file__).read_text(), capture_output=True, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SessionError(f"the session to {canary} did not finish within {timeout:g} seconds") from exc
    except FileNotFoundError as exc:
        raise SessionError(f"can't run {argv[0]}: {exc}") from exc
    results = {}
    for line in done.stdout.splitlines():
        if not line.strip():
            continue
        try:
            result = json.loads(line)
            results[result["id"]] = result
        except (ValueError, KeyError, TypeError) as exc:
            raise SessionError(f"the session to {canary} printed a line that is not a result: {line[:80]!r}") from exc
    if done.returncode != 0 and not results:
        raise SessionError(f"the session to {canary} failed with status {done.returncode}: {done.stderr.strip()[-200:]}")
    return results


def evaluate(flows: list[Flow], results: dict[str, dict[str, str]], failures: dict[str, str]) -> list[Outcome]:
    """Decide each flow. `failures` has the reason a flow has no result, by flow id."""
    allows = {flow.id for flow in flows if flow.expect == "allow"}
    outcomes = []
    for flow in flows:
        result = results.get(flow.id)
        if result is None:
            outcomes.append(Outcome(flow.id, False, f"no result: {failures.get(flow.id, 'the canary did not report it')}"))
        elif result["status"] == probe.ERROR:
            outcomes.append(Outcome(flow.id, False, f"the probe could not be run: {result['detail']}"))
        elif flow.expect == "allow":
            succeeded = result["status"] == probe.OK
            outcomes.append(Outcome(flow.id, succeeded, "allowed" if succeeded else f"blocked: {result['detail']}"))
        elif flow.control not in allows or results.get(flow.control, {}).get("status") != probe.OK:
            outcomes.append(Outcome(flow.id, False, f"its control {flow.control} failed, so a block is not shown"))
        elif result["status"] == probe.OK:
            outcomes.append(Outcome(flow.id, False, "the attempt succeeded"))
        else:
            outcomes.append(Outcome(flow.id, True, f"blocked: {result['detail']}"))
    return outcomes


def execute(
    flow_list: FlowList,
    flows: list[Flow],
    user: str,
    ssh_command: list[str],
    python: str = "python3",
    timeout: float = PROBE_TIMEOUT,
    zone_users: Mapping[str, str] | None = None,
) -> list[Outcome]:
    """Try `flows` from their canaries, one session per source zone, and decide each.

    `zone_users` names the user to log in as for a zone whose canary is not like the others (a VM with its own admin account)."""
    results: dict[str, dict[str, str]] = {}
    failures: dict[str, str] = {}
    for zone in dict.fromkeys(flow.source for flow in flows):
        zone_flows = [flow for flow in flows if flow.source == zone]
        specs = [_spec(flow, timeout) for flow in zone_flows]
        try:
            canary = str(flow_list.zones[zone].canary)
            results.update(run_session(canary, (zone_users or {}).get(zone, user), ssh_command, python, specs, timeout * len(specs) + SESSION_MARGIN))
        except SessionError as exc:
            failures.update({flow.id: str(exc) for flow in zone_flows})
    return evaluate(flows, results, failures)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Try the flows of the flow list from the canaries.")
    parser.add_argument("--ssh-user", required=True, help="the user to log in to each canary as")
    parser.add_argument("--ssh-user-for", action="append", default=[], metavar="ZONE=USER", help="log in to this zone's canary as USER instead (repeatable)")
    parser.add_argument("--ssh-command", default=DEFAULT_SSH_COMMAND, help="the ssh command and options, before user@canary")
    parser.add_argument("--remote-python", default="python3", help="the canary's Python")
    parser.add_argument("--tag", action="append", default=[], help="run the flows with this tag (repeatable)")
    parser.add_argument("--flow", action="append", default=[], help="run this flow by id (repeatable)")
    parser.add_argument("--without-canary", action="append", default=[], metavar="ZONE", help="leave out the flows that need this zone's canary (repeatable)")
    parser.add_argument("--flows", type=Path, default=FLOWS_PATH, help="the flow list (default: the committed one)")
    args = parser.parse_args(argv)
    zone_users = dict(item.partition("=")[::2] for item in args.ssh_user_for)
    if any(not zone or not user for zone, user in zone_users.items()) or len(zone_users) != len(args.ssh_user_for):
        print("--ssh-user-for takes ZONE=USER, once per zone", file=sys.stderr)
        return 2
    try:
        flow_list = load_flow_list(args.flows)
    except FlowListError as exc:
        print("\n".join(exc.problems), file=sys.stderr)
        return 2
    unknown = sorted(set(zone_users) - set(flow_list.zones))
    if unknown:
        print(f"--ssh-user-for names a zone the flow list does not have: {', '.join(unknown)}", file=sys.stderr)
        return 2
    unknown = sorted(set(args.without_canary) - set(flow_list.zones))
    if unknown:
        print(f"--without-canary names a zone the flow list does not have: {', '.join(unknown)}", file=sys.stderr)
        return 2
    violations = rules.check(flow_list)
    if violations:
        print("\n".join(f"{v.name}: [{v.rule}] {v.message}" for v in violations), file=sys.stderr)
        return 2
    try:
        flows = select(flow_list, args.tag, args.flow, args.without_canary)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not flows:
        print("no flow is selected, so nothing was shown", file=sys.stderr)
        return 2
    outcomes = execute(flow_list, flows, args.ssh_user, shlex.split(args.ssh_command), args.remote_python, zone_users=zone_users)
    for outcome in outcomes:
        print(f"{'PASS' if outcome.passed else 'FAIL'} {outcome.flow_id}: {outcome.message}")
    failed = [outcome for outcome in outcomes if not outcome.passed]
    print(f"{len(outcomes) - len(failed)} of {len(outcomes)} flows passed")
    if args.without_canary:
        left_out = len(select(flow_list, args.tag, args.flow)) - len(flows)
        print(f"flows left out: {left_out}, needing the canary of: {', '.join(sorted(set(args.without_canary)))}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
