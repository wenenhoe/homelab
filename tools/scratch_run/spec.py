"""The written spec of a scratch-gateway run.

A spec is a YAML file: the seed's VLANs and the play's variables, an optional block rule, and the steps to take in
order. `load_spec` refuses a file whose shape is wrong or that names a flow the flow list does not have, and says
every problem at once, so a mistake costs no gateway build. Standard library and PyYAML only.

    name: rehearsal
    description: what the run shows
    gateway:
      vlans: [20, 25, 40, 50, 55, 30]   # optional: the seed's VLAN list
      play_vars: {opnsense_gateway_...: ...}  # optional: the play's -e variables
    block_rule: {source: ..., destination: ..., protocol: UDP, port: 53}
    canary_vm: {zone: services}   # optional: a scratch VM takes that zone's canary address
    steps:
      - {id: play-apply, play: apply}                    # apply | check; expect: ok | unchanged | changed
      - {id: services, flows: {tags: [services]}}        # tags and/or ids; expect: pass | fail
      - {id: block-on, block: present}                   # present | absent, needs block_rule
      - {id: vlans, vlans: check}                        # the gateway has the VLAN interfaces `gateway.vlans` seeds
      - {id: canary-vm, vm: up}                          # builds the canary VM and waits for it to answer over ssh; before any flows step
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from network_checks.flow_list import FLOWS_PATH, FlowListError, load_flow_list
from network_checks.scratch_plan import zone_vlans
from utils.unique_key_yaml import UniqueKeyLoader

from scratch_run import canary_vm

NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
STEP_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
TOP_KEYS = ("name", "description", "gateway", "block_rule", "canary_vm", "steps")
GATEWAY_KEYS = ("vlans", "play_vars")
RULE_KEYS = ("source", "destination", "protocol", "port")
CANARY_VM_KEYS = ("zone",)
STEP_KEYS = ("id", "play", "flows", "block", "vlans", "vm", "expect")
FLOWS_KEYS = ("tags", "ids")
KINDS = ("play", "flows", "block", "vlans", "vm")
MODES = {"play": ("apply", "check"), "block": ("present", "absent"), "vlans": ("check",), "vm": ("up",)}
NO_EXPECT = {
    "block": "a block step passes when the playbook succeeds",
    "vlans": "a vlans step passes when the gateway has the VLAN interfaces",
    "vm": "a vm step passes when the VM answers over ssh",
}
EXPECTS = {"play": ("ok", "unchanged", "changed"), "flows": ("pass", "fail")}
DEFAULT_EXPECT = {"apply": "ok", "check": "unchanged", "flows": "pass"}
# The backend sets these three itself, so a spec that sets them would be overridden or would override.
BACKEND_VARS = ("opnsense_gateway_ca_file", "opnsense_gateway_api_port", "opnsense_gateway_credentials_file")
PLAY_VAR_PREFIX = "opnsense_gateway_"


class SpecError(Exception):
    """The spec is wrong; the message lists every problem found."""


@dataclass(frozen=True)
class BlockRule:
    source: str
    destination: str
    protocol: str
    port: int


@dataclass(frozen=True)
class Step:
    id: str
    kind: str  # play, flows, block, vlans or vm
    mode: str  # apply, check, present, absent or up; empty for flows
    expect: str  # ok, unchanged, changed, pass or fail; empty for block, vlans and vm
    tags: tuple[str, ...] = ()
    flow_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanaryVm:
    zone: str


@dataclass(frozen=True)
class Spec:
    name: str
    description: str
    vlans: tuple[int, ...]
    play_vars: dict[str, object]
    block_rule: BlockRule | None
    steps: tuple[Step, ...]
    canary_vm: CanaryVm | None = None


def _unknown(where: str, raw: dict, allowed: tuple[str, ...], problems: list[str]) -> None:
    for key in raw:
        if key not in allowed:
            problems.append(f"{where} has the unknown key `{key}`; the keys are {', '.join(allowed)}")


def _strings(value: object) -> list[str] | None:
    return value if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value) else None


def _vlans(raw: object, problems: list[str]) -> tuple[int, ...]:
    if raw is None:
        return ()
    ok = isinstance(raw, list) and raw and all(isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 4094 for v in raw)
    if not ok or len(set(raw)) != len(raw):
        problems.append("`gateway.vlans` must be a list of distinct VLAN tags, each 1 to 4094")
        return ()
    return tuple(raw)


def _play_vars(raw: object, problems: list[str]) -> dict[str, object]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        problems.append("`gateway.play_vars` must be a mapping")
        return {}
    for key in raw:
        if not (isinstance(key, str) and key.startswith(PLAY_VAR_PREFIX)):
            problems.append(f"`gateway.play_vars` may set only variables that start with `{PLAY_VAR_PREFIX}`, not `{key}`")
        elif key in BACKEND_VARS:
            problems.append(f"`gateway.play_vars` may not set `{key}`, which the backend sets")
    try:
        json.dumps(raw)
    except TypeError:
        problems.append("`gateway.play_vars` must hold only values JSON can carry")
    return raw


def _network(value: object) -> bool:
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError, TypeError:
        return False
    return True


def _block_rule(raw: object, problems: list[str]) -> BlockRule | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        problems.append("`block_rule` must be a mapping")
        return None
    _unknown("`block_rule`", raw, RULE_KEYS, problems)
    before = len(problems)
    for key in ("source", "destination"):
        if not _network(raw.get(key)):
            problems.append(f"`block_rule.{key}` must be an IPv4 address or network")
    if raw.get("protocol") not in ("TCP", "UDP"):
        problems.append("`block_rule.protocol` must be TCP or UDP")
    port = raw.get("port")
    if not (isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535):
        problems.append("`block_rule.port` must be a port number")
    if len(problems) > before:
        return None
    return BlockRule(raw["source"], raw["destination"], raw["protocol"], raw["port"])


def _canary_vm(raw: object, problems: list[str]) -> CanaryVm | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        problems.append("`canary_vm` must be a mapping")
        return None
    _unknown("`canary_vm`", raw, CANARY_VM_KEYS, problems)
    zone = raw.get("zone")
    if not (isinstance(zone, str) and zone):
        problems.append("`canary_vm.zone` must name a zone of the flow list")
        return None
    return CanaryVm(zone)


def _step(raw: object, index: int, problems: list[str]) -> Step | None:
    where = f"step {index}"
    if not isinstance(raw, dict):
        problems.append(f"{where} must be a mapping")
        return None
    step_id = raw.get("id")
    if not (isinstance(step_id, str) and STEP_ID_RE.fullmatch(step_id)):
        problems.append(f"{where} needs an `id` of lowercase letters, digits and hyphens")
        step_id = f"#{index}"
    where = f"step `{step_id}`"
    _unknown(where, raw, STEP_KEYS, problems)
    kinds = [kind for kind in KINDS if kind in raw]
    if len(kinds) != 1:
        problems.append(f"{where} needs exactly one of {', '.join(KINDS)}")
        return None
    kind = kinds[0]
    expect = raw.get("expect")
    if kind == "flows":
        flows = raw["flows"]
        if not isinstance(flows, dict) or not flows or any(key not in FLOWS_KEYS for key in flows):
            problems.append(f"{where} needs `flows` to be a mapping of `tags` and/or `ids`")
            return None
        lists = {key: _strings(flows[key]) for key in flows}
        if any(value is None for value in lists.values()):
            problems.append(f"{where} needs each of `flows.tags` and `flows.ids` to be a non-empty list of names")
            return None
        mode = ""
        expect = expect or DEFAULT_EXPECT["flows"]
        tags, ids = tuple(lists.get("tags", ())), tuple(lists.get("ids", ()))
    else:
        mode = raw[kind]
        tags = ids = ()
        if mode not in MODES[kind]:
            problems.append(f"{where} needs `{kind}` to be one of {', '.join(MODES[kind])}")
            return None
        if kind in NO_EXPECT:
            if expect is not None:
                problems.append(f"{where} takes no `expect`: {NO_EXPECT[kind]}")
            expect = ""
        else:
            expect = expect or DEFAULT_EXPECT[mode]
    if kind not in NO_EXPECT and expect not in EXPECTS[kind]:
        problems.append(f"{where} needs `expect` to be one of {', '.join(EXPECTS[kind])}")
        return None
    return Step(step_id, kind, mode, expect, tags, ids)


def _check_flows(steps: list[Step], flows_path: Path, problems: list[str]) -> None:
    wanted = [step for step in steps if step.kind == "flows"]
    if not wanted:
        return
    try:
        flow_list = load_flow_list(flows_path)
    except FlowListError as error:
        problems.append(f"the flow list cannot be read: {error}")
        return
    known_ids = {flow.id for flow in flow_list.flows}
    known_tags = {tag for flow in flow_list.flows for tag in flow.tags}
    for step in wanted:
        problems.extend(f"step `{step.id}` names the tag `{tag}`, which no flow has" for tag in step.tags if tag not in known_tags)
        problems.extend(f"step `{step.id}` names the flow `{flow}`, which the flow list does not have" for flow in step.flow_ids if flow not in known_ids)


def _check_canary_vm(vm: CanaryVm, vlans: tuple[int, ...], steps: list[Step], flows_path: Path, problems: list[str]) -> None:
    vm_steps = [index for index, step in enumerate(steps) if step.kind == "vm"]
    if not vm_steps:
        problems.append("`canary_vm` is set and no step uses it")
    if len(vm_steps) > 1:
        problems.append("at most one step may be a vm step")
    if vm_steps and any(step.kind == "flows" for step in steps[: vm_steps[0]]):
        problems.append("the vm step must come before every flows step, which build the namespace canaries the VM replaces one of")
    try:
        found = canary_vm.vm_id(vm.zone, load_flow_list(flows_path), zone_vlans())
    except FlowListError as error:
        problems.append(f"the flow list cannot be read: {error}")
    except ValueError as error:
        problems.append(f"`canary_vm.zone`: {error}")
    else:
        if vlans and found // 50 * 5 not in vlans:
            problems.append(f"`canary_vm.zone` `{vm.zone}` is on VLAN {found // 50 * 5}, which `gateway.vlans` does not carry")


def parse_spec(data: object, flows_path: Path = FLOWS_PATH) -> Spec:
    """The spec `data` describes, or a `SpecError` naming every problem."""
    if not isinstance(data, dict):
        raise SpecError("the spec must be a mapping")
    problems: list[str] = []
    _unknown("the spec", data, TOP_KEYS, problems)
    name = data.get("name")
    if not (isinstance(name, str) and NAME_RE.fullmatch(name)):
        problems.append("`name` must be lowercase letters, digits and hyphens, starting with a letter")
        name = ""
    description = data.get("description")
    if not (isinstance(description, str) and description.strip()):
        problems.append("`description` must say what the run shows")
        description = ""
    gateway = data.get("gateway") or {}
    if not isinstance(gateway, dict):
        problems.append("`gateway` must be a mapping")
        gateway = {}
    _unknown("`gateway`", gateway, GATEWAY_KEYS, problems)
    vlans = _vlans(gateway.get("vlans"), problems)
    play_vars = _play_vars(gateway.get("play_vars"), problems)
    rule = _block_rule(data.get("block_rule"), problems)
    vm = _canary_vm(data.get("canary_vm"), problems)
    raw_steps = data.get("steps")
    steps: list[Step] = []
    if not (isinstance(raw_steps, list) and raw_steps):
        problems.append("`steps` must be a non-empty list")
    else:
        steps = [step for index, raw in enumerate(raw_steps, 1) if (step := _step(raw, index, problems))]
    ids = [step.id for step in steps]
    problems.extend(f"the step id `{step_id}` is used twice" for step_id in sorted({i for i in ids if ids.count(i) > 1}))
    uses_block = any(step.kind == "block" for step in steps)
    if uses_block and "block_rule" not in data:
        problems.append("a block step needs `block_rule`")
    if rule is not None and not uses_block:
        problems.append("`block_rule` is set and no step uses it")
    if vm is not None:
        _check_canary_vm(vm, vlans, steps, flows_path, problems)
    elif any(step.kind == "vm" for step in steps):
        problems.append("a vm step needs `canary_vm`, the zone whose canary the VM replaces")
    if any(step.kind == "vlans" for step in steps) and not vlans:
        problems.append("a vlans step needs `gateway.vlans`, the list it compares the gateway with")
    _check_flows(steps, flows_path, problems)
    if problems:
        raise SpecError("\n".join(problems))
    return Spec(name, description.strip(), vlans, play_vars, rule, tuple(steps), vm)


def load_spec(path: Path, flows_path: Path = FLOWS_PATH) -> Spec:
    try:
        data = yaml.load(path.read_text(), Loader=UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except (OSError, yaml.YAMLError) as error:
        raise SpecError(f"{path} cannot be read: {error}") from error
    return parse_spec(data, flows_path)
