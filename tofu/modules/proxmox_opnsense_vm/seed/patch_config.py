#!/usr/bin/env python3
"""Turn OPNsense's sample config.xml into the gateway's seed configuration.

Assigns the WAN and LAN devices and the LAN address, turns IPv6 off, adds one VLAN device and
interface per zone on the LAN device, sets the hostname and domain, keeps the serial port as the console, gives root a password and adds one
API user whose key and secret are stored the way OPNsense stores them (the
secret as a SHA-512 crypt hash, see ApiKeyField::add in opnsense/core).

The root password, API key and API secret are read from the Tofu credentials
file (ADR 0048) and generated into it when it holds none of them, so a rebuilt
gateway keeps the credentials the play already holds. The seed carries only
hashes.
"""

import argparse
import base64
import ipaddress
import os
import re
import secrets
import stat
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

CREDENTIAL_NAMES = ("opnsense_root_password", "opnsense_api_key", "opnsense_api_secret")
DEFAULT_CREDENTIALS = "~/.config/tofu/credentials.tfvars"
BASE = Path(__file__).with_name("config.xml.sample")
# One VLAN per VMID hundred (vlan_id = vmid // 100 * 10), each a /24 whose
# third octet is the tag and whose gateway address is .1.
DEFAULT_VLANS = (20, 30, 40, 50, 60)
VLAN_NAMESPACE = uuid.UUID("5d0c7a52-3c1e-4a53-9a0f-6a4a3f0f6a11")
ASSIGNMENT = re.compile(r'^\s*(\w+)\s*=\s*"([^"\\]*)"\s*(?:#.*)?$')


def crypt_sha512(clear: str) -> str:
    # The password goes in on stdin so it never shows in the process list.
    done = subprocess.run(["openssl", "passwd", "-6", "-stdin"], input=clear + "\n", capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SystemExit(f"openssl passwd failed: {done.stderr.strip()}")
    return done.stdout.strip()


def read_credentials(path: Path) -> dict[str, str]:
    """The seed's three credentials as the file holds them; empty when it has none or does not exist."""
    if not path.exists():
        return {}
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise SystemExit(f"{path} is readable by others; chmod 600 it")
    found = {}
    for line in path.read_text().splitlines():
        m = ASSIGNMENT.match(line)
        if m and m[1] in CREDENTIAL_NAMES:
            found[m[1]] = m[2]
    return found


def ensure_credentials(path: Path) -> dict[str, str]:
    """Return the three credentials, appending generated ones to the file when it holds none of them."""
    found = read_credentials(path)
    if len(found) == len(CREDENTIAL_NAMES):
        return found
    if found:
        missing = ", ".join(n for n in CREDENTIAL_NAMES if n not in found)
        raise SystemExit(f"{path} holds some of the OPNsense credentials but not {missing}; set all three or none")
    generated = {
        "opnsense_root_password": base64.urlsafe_b64encode(secrets.token_bytes(12)).decode(),
        "opnsense_api_key": base64.b64encode(secrets.token_bytes(60)).decode(),
        "opnsense_api_secret": base64.b64encode(secrets.token_bytes(60)).decode(),
    }
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    separator = "" if existing.endswith("\n") or not existing else "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as fh:
        fh.write(separator + "".join(f'{name} = "{value}"\n' for name, value in generated.items()))
    return generated


def set_text(parent: ET.Element, tag: str, value: str) -> ET.Element:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = value
    return el


def remove(parent: ET.Element, *tags: str) -> None:
    for tag in tags:
        for el in parent.findall(tag):
            parent.remove(el)


def add_vlans(root: ET.Element, lan_if: str, lan_ip: str, lan_prefix: str, tags: Sequence[int]) -> None:
    """Add a VLAN device on the LAN device and an interface carrying its gateway address, for each tag.

    The devices are named vlan0.<tag> and the interfaces opt1, opt2, ... in the order given.
    """
    if len(set(tags)) != len(tags) or any(not 2 <= tag <= 254 for tag in tags):
        raise SystemExit(f"VLAN tags must be distinct numbers from 2 to 254, got {list(tags)}")
    lan_net = ipaddress.ip_network(f"{lan_ip}/{lan_prefix}", strict=False)
    for tag in tags:
        if ipaddress.ip_network(f"192.168.{tag}.0/24").overlaps(lan_net):
            raise SystemExit(f"the LAN network {lan_net} overlaps VLAN {tag}'s 192.168.{tag}.0/24")
    if not tags:
        return
    interfaces = root.find("interfaces")
    vlans = ET.Element("vlans", {"version": "1.0.0"})
    for number, tag in enumerate(tags, start=1):
        vlan = ET.SubElement(vlans, "vlan", {"uuid": str(uuid.uuid5(VLAN_NAMESPACE, f"{lan_if}.{tag}"))})
        set_text(vlan, "if", lan_if)
        set_text(vlan, "tag", str(tag))
        set_text(vlan, "pcp", "0")
        set_text(vlan, "proto", "")
        set_text(vlan, "descr", f"VM ID {tag // 10}XX")
        set_text(vlan, "vlanif", f"vlan0.{tag}")
        opt = ET.SubElement(interfaces, f"opt{number}")
        set_text(opt, "if", f"vlan0.{tag}")
        set_text(opt, "descr", f"OPT{number}")
        set_text(opt, "enable", "1")
        set_text(opt, "ipaddr", f"192.168.{tag}.1")
        set_text(opt, "subnet", "24")
    root.insert(list(root).index(interfaces) + 1, vlans)


def build_seed(
    base: Path,
    creds: dict[str, str],
    *,
    wan_if: str,
    lan_if: str,
    lan_ip: str,
    lan_prefix: str,
    hostname: str,
    domain: str,
    api_user: str,
    wan_dhcp_hostname: str | None,
    vlans: Sequence[int] = DEFAULT_VLANS,
) -> ET.ElementTree:
    tree = ET.parse(base)  # noqa: S314 - the sample configuration shipped beside this script
    root = tree.getroot()
    system = root.find("system")

    set_text(system, "hostname", hostname)
    set_text(system, "domain", domain)

    # Root keeps its group and uid; only the password changes.
    for user in system.findall("user"):
        if user.findtext("name") == "root":
            set_text(user, "password", crypt_sha512(creds["opnsense_root_password"]))

    api = ET.Element("user")
    set_text(api, "name", api_user)
    set_text(api, "descr", "API user of the configuration play")
    set_text(api, "scope", "user")
    # The account cannot log in: its password is a hash of random bytes.
    set_text(api, "password", crypt_sha512(base64.b64encode(secrets.token_bytes(32)).decode()))
    set_text(api, "uid", "2000")
    set_text(api, "priv", "page-all")
    item = ET.SubElement(ET.SubElement(api, "apikeys"), "item")
    set_text(item, "key", creds["opnsense_api_key"])
    set_text(item, "secret", crypt_sha512(creds["opnsense_api_secret"]))
    # Users sit after the groups, before the remaining system settings.
    users = system.findall("user")
    system.insert(list(system).index(users[-1]) + 1, api)
    set_text(system, "nextuid", "2001")

    # The image keeps these in its own configuration, which the seed replaces, so
    # without them the serial console goes silent.
    set_text(system, "serialspeed", "115200")
    set_text(system, "primaryconsole", "serial")
    set_text(system, "secondaryconsole", "video")

    interfaces = root.find("interfaces")
    wan = interfaces.find("wan")
    set_text(wan, "if", wan_if)
    if wan_dhcp_hostname is not None:
        set_text(wan, "dhcphostname", wan_dhcp_hostname)
    lan = interfaces.find("lan")
    set_text(lan, "if", lan_if)
    set_text(lan, "ipaddr", lan_ip)
    set_text(lan, "subnet", lan_prefix)
    # IPv6 is off while unused: the system-wide switch goes, and neither interface asks for or tracks an IPv6 address.
    remove(system, "ipv6allow")
    remove(wan, "ipaddrv6", "dhcp6-ia-pd-len")
    remove(lan, "ipaddrv6", "subnetv6", "track6-interface", "track6-prefix-id")
    add_vlans(root, lan_if, lan_ip, lan_prefix, vlans)

    ET.indent(tree, space="  ")
    return tree


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="where to write the seed config.xml")
    ap.add_argument("--base", type=Path, default=BASE, help="the sample configuration to start from")
    ap.add_argument("--credentials", default=DEFAULT_CREDENTIALS, help="the Tofu credentials file holding or receiving the three OPNsense credentials")
    ap.add_argument("--lan-ip", required=True)
    ap.add_argument("--lan-prefix", default="24")
    ap.add_argument("--wan-if", default="vtnet0", help="the device of the module's first NIC")
    ap.add_argument("--lan-if", default="vtnet1", help="the device of the module's second NIC")
    ap.add_argument("--vlans", default=",".join(map(str, DEFAULT_VLANS)), help="comma-separated VLAN tags to add on the LAN device, none when empty")
    ap.add_argument("--hostname", default="OPNsense")
    ap.add_argument("--domain", default="internal", help="with the hostname, the management name the play verifies the GUI certificate for")
    ap.add_argument("--api-user", default="ansible")
    ap.add_argument("--wan-dhcp-hostname", help="the name the WAN's DHCP lease is registered under; the sample's empty value when omitted")
    a = ap.parse_args(argv)

    try:
        vlans = [int(tag) for tag in a.vlans.split(",") if tag.strip()]
    except ValueError:
        ap.error(f"--vlans takes comma-separated numbers, got {a.vlans!r}")
    creds = ensure_credentials(Path(a.credentials).expanduser())
    tree = build_seed(
        a.base,
        creds,
        wan_if=a.wan_if,
        lan_if=a.lan_if,
        lan_ip=a.lan_ip,
        lan_prefix=a.lan_prefix,
        hostname=a.hostname,
        domain=a.domain,
        api_user=a.api_user,
        wan_dhcp_hostname=a.wan_dhcp_hostname,
        vlans=vlans,
    )
    tree.write(a.out, encoding="UTF-8", xml_declaration=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
