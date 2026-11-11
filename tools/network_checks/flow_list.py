"""The reader of the flow list in flows.yaml (ADR 0094).

Standard library and PyYAML only, so a pre-commit hook can import it. `load_flow_list` refuses a file whose
shape is wrong, naming every problem it finds: a misspelt key would otherwise be ignored, and a flow with no
port could not be tried. What the flows say about each other is the business of rules.py.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from utils.unique_key_yaml import UniqueKeyLoader

FLOWS_PATH = Path(__file__).resolve().with_name("flows.yaml")
KINDS = ("connect", "dns", "ping", "ntp")
EXPECTS = ("allow", "deny")
# The protocols a kind may name. The first is the default, and `dns` has none because a query needs it said.
PROTOCOLS = {"connect": ("tcp",), "dns": ("udp", "tcp"), "ntp": ("udp",), "ping": ()}
DEFAULT_PROTOCOL = {"connect": "tcp", "ntp": "udp"}
ZONE_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
FLOW_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
HOSTNAME_RE = re.compile(r"(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*")
TOP_KEYS = ("zones", "flows")
ZONE_KEYS = ("subnet", "canary")
FLOW_KEYS = ("id", "from", "to", "kind", "query", "expect", "control", "tags")
DESTINATION_KEYS = ("address", "port", "protocol")


@dataclass(frozen=True)
class Zone:
    name: str
    subnet: ipaddress.IPv4Network
    canary: ipaddress.IPv4Address


@dataclass(frozen=True)
class Destination:
    address: str  # an IPv4 address or a host name
    port: int | None  # none for ping
    protocol: str | None  # none for ping

    def ip(self) -> ipaddress.IPv4Address | None:
        """The address as an IPv4 address, or none when it is a name."""
        try:
            return ipaddress.IPv4Address(self.address)
        except ValueError:
            return None


@dataclass(frozen=True)
class Flow:
    id: str
    source: str  # the zone whose canary makes the attempt
    destination: Destination
    kind: str
    expect: str
    control: str | None
    query: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class FlowList:
    zones: dict[str, Zone]
    flows: tuple[Flow, ...]


class FlowListError(Exception):
    """The flow list can't be read, or its shape is wrong. `problems` has one line for each thing found."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _label(path: Path) -> str:
    return path.name


def _keys_problems(value: dict[object, object], allowed: tuple[str, ...], where: str) -> list[str]:
    return [f"{where} has the unknown key `{key}`" for key in value if key not in allowed]


def _parse_zone(name: object, raw: object, problems: list[str]) -> Zone | None:
    where = f"zone `{name}`"
    if not isinstance(name, str) or not ZONE_NAME_RE.fullmatch(name):
        problems.append(f"{where} must be named in lower-case letters, digits and hyphens, starting with a letter")
        return None
    if not isinstance(raw, dict):
        problems.append(f"{where} must be a mapping with a subnet and a canary")
        return None
    problems.extend(_keys_problems(raw, ZONE_KEYS, where))
    subnet = canary = None
    try:
        subnet = ipaddress.IPv4Network(str(raw.get("subnet")))
    except ValueError:
        problems.append(f"{where} needs a `subnet` that is an IPv4 network such as 192.168.20.0/24")
    try:
        canary = ipaddress.IPv4Address(str(raw.get("canary")))
    except ValueError:
        problems.append(f"{where} needs a `canary` that is an IPv4 address")
    if subnet is not None and canary is not None and canary not in subnet:
        problems.append(f"{where} has the canary {canary}, which is not inside {subnet}")
    if subnet is None or canary is None or canary not in subnet:
        return None
    return Zone(name, subnet, canary)


def _parse_destination(raw: object, kind: object, where: str, problems: list[str]) -> Destination | None:
    if not isinstance(raw, dict):
        problems.append(f"{where} needs `to` as a mapping with an address, and a port and protocol unless the kind is ping")
        return None
    problems.extend(_keys_problems(raw, DESTINATION_KEYS, f"{where}'s `to`"))
    address = raw.get("address")
    if not isinstance(address, str) or not address:
        problems.append(f"{where} needs `to.address`, an IPv4 address or a name")
        return None
    try:
        ipaddress.IPv4Address(address)
    except ValueError:
        if not HOSTNAME_RE.fullmatch(address) or address.replace(".", "").isdigit():
            problems.append(f"{where} has `to.address` {address!r}, which is neither an IPv4 address nor a host name")
            return None
    if kind not in KINDS:
        return None
    port, protocol = raw.get("port"), raw.get("protocol")
    if kind == "ping":
        if port is not None or protocol is not None:
            problems.append(f"{where} is a ping, which takes no port or protocol")
            return None
        return Destination(address, None, None)
    ok = True
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        problems.append(f"{where} needs `to.port` between 1 and 65535")
        ok = False
    protocol = DEFAULT_PROTOCOL.get(str(kind)) if protocol is None else protocol
    if protocol not in PROTOCOLS[str(kind)]:
        problems.append(f"{where} is a {kind} flow, so `to.protocol` must be one of {', '.join(PROTOCOLS[str(kind)])}")
        ok = False
    return Destination(address, port, protocol) if ok else None


def _parse_flow(raw: object, index: int, problems: list[str]) -> Flow | None:
    if not isinstance(raw, dict):
        problems.append(f"flow {index + 1} must be a mapping")
        return None
    flow_id = raw.get("id")
    where = f"flow `{flow_id}`" if isinstance(flow_id, str) else f"flow {index + 1}"
    problems.extend(_keys_problems(raw, FLOW_KEYS, where))
    before = len(problems)
    if not isinstance(flow_id, str) or not FLOW_ID_RE.fullmatch(flow_id):
        problems.append(f"{where} needs an `id` in lower-case letters, digits, dots, underscores and hyphens")
    source = raw.get("from")
    if not isinstance(source, str) or not source:
        problems.append(f"{where} needs `from`, the name of the source zone")
    kind, expect = raw.get("kind"), raw.get("expect")
    if kind not in KINDS:
        problems.append(f"{where} needs `kind` to be one of {', '.join(KINDS)}")
    if expect not in EXPECTS:
        problems.append(f"{where} needs `expect` to be allow or deny")
    destination = _parse_destination(raw.get("to"), kind, where, problems)
    control, query = raw.get("control"), raw.get("query")
    if expect == "deny" and not (isinstance(control, str) and control):
        problems.append(f"{where} is a deny and needs a `control`, the id of an allow flow")
    if expect == "allow" and control is not None:
        problems.append(f"{where} is an allow and takes no `control`")
    if kind == "dns" and not (isinstance(query, str) and HOSTNAME_RE.fullmatch(query)):
        problems.append(f"{where} is a dns flow and needs a `query`, the name to ask for")
    if kind != "dns" and query is not None:
        problems.append(f"{where} takes a `query` only when it is a dns flow")
    tags = raw.get("tags", [])
    if not (isinstance(tags, list) and all(isinstance(tag, str) and tag for tag in tags)):
        problems.append(f"{where} needs `tags` to be a list of labels")
        tags = []
    if len(problems) > before or destination is None:
        return None
    return Flow(
        str(flow_id),
        str(source),
        destination,
        str(kind),
        str(expect),
        control if isinstance(control, str) else None,
        query if isinstance(query, str) else None,
        tuple(tags),
    )


def load_flow_list(path: Path = FLOWS_PATH) -> FlowList:
    """The zones and flows in `path`. A repeated key, an unknown key or a field of the wrong shape is an error."""
    label = _label(path)
    try:
        data = yaml.load(path.read_text(), Loader=UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except OSError as exc:
        raise FlowListError([f"can't read {label}: {exc}"]) from exc
    except yaml.YAMLError as exc:
        raise FlowListError([f"{label} isn't valid YAML: {exc}"]) from exc
    if not isinstance(data, dict):
        raise FlowListError([f"{label} must be a mapping with `zones` and `flows`"])
    problems = _keys_problems(data, TOP_KEYS, label)
    zones_raw, flows_raw = data.get("zones"), data.get("flows")
    if not isinstance(zones_raw, dict):
        problems.append("`zones` must be a mapping of zone name to its subnet and canary")
        zones_raw = {}
    if not isinstance(flows_raw, list):
        problems.append("`flows` must be a list")
        flows_raw = []
    zones = {}
    for name, raw in zones_raw.items():
        zone = _parse_zone(name, raw, problems)
        if zone is not None:
            zones[name] = zone
    flows = tuple(flow for index, raw in enumerate(flows_raw) if (flow := _parse_flow(raw, index, problems)) is not None)
    if problems:
        raise FlowListError(problems)
    return FlowList(zones, flows)
