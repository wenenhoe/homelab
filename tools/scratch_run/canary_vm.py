"""The scratch VM that stands in for one zone's canary, and what it takes to make it.

A zone's canary sits at its `.8` (the flow list), and the lab's VMID scheme (`proxmox_ubuntu_vm`) puts a VM's VLAN in the block of 50
of its VMID (`vlan = vmid // 50 * 5`) and its host address in the remainder. So the canary of the zone on VLAN 20 is VM 208,
and a scratch VM built with that VMID on the scratch gateway's bridge takes the canary's address, carries the zone's tag and is
reached by the runner as a canary VM is. Standard library, `network_checks` and nothing else.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from pathlib import Path

from network_checks.flow_list import FlowList

ADMIN_USER = "scratch"  # `tofu/scratch/ubuntu`'s admin_username; the runner logs in to the VM as this account
DNS_DOMAIN = "scratch.lab"  # the search domain the module requires; nothing on a scratch gateway resolves it
VM_NAME_PREFIX = "canary-"
HOST_OCTET_LIMIT = 50  # the scheme keeps a host's address in the VMID's remainder after dividing by 50


def vm_id(zone: str, flow_list: FlowList, vlans: Mapping[str, int]) -> int:
    """The VMID whose scheme address is the canary of `zone`; raises ValueError saying why when none is."""
    if zone not in flow_list.zones:
        raise ValueError(f"the zone `{zone}` is not in the flow list (it has {', '.join(flow_list.zones)})")
    vlan = vlans.get(zone)
    if vlan is None:
        raise ValueError(f"the gateway's play has no zone `{zone}`, so its VLAN is not known")
    canary = flow_list.zones[zone].canary
    host = int(canary) & 0xFF
    if vlan % 5 or canary not in ipaddress.ip_network(f"192.168.{vlan}.0/24") or host >= HOST_OCTET_LIMIT:
        raise ValueError(f"the canary {canary} of `{zone}` is not an address a VMID of the lab's scheme gives on VLAN {vlan}")
    return vlan * 10 + host


def tfvars(vm: int, zone: str, bridge: str, public_key: str, node_name: str, template_vm_id: str = "") -> dict[str, object]:
    """The variables `tofu/scratch/ubuntu` takes for this VM, as a JSON var-file holds them."""
    values: dict[str, object] = {
        "vm_id": vm,
        "name": f"{VM_NAME_PREFIX}{zone}",
        "lan_bridge": bridge,
        "node_name": node_name,
        "admin_username": ADMIN_USER,
        "ssh_public_keys": [public_key.strip()],
        "dns_domain": DNS_DOMAIN,
    }
    if template_vm_id:
        values["template_vm_id"] = int(template_vm_id)
    return values


def public_key_of(path: Path) -> str:
    """The one public key line in `path`."""
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if len(lines) != 1 or not re.fullmatch(r"ssh-\S+ \S+( .*)?", lines[0]):
        raise ValueError(f"{path} does not hold exactly one ssh public key")
    return lines[0]
