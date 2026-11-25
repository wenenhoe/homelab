#!/usr/bin/env python3
"""Turn OPNsense's sample config.xml into the gateway's seed configuration.

Assigns the WAN and LAN devices and the LAN address, turns IPv6 off, puts a one-time password in front of the GUI login, adds one VLAN device and
interface per VLAN on the LAN device, sets the hostname, domain and time zone, keeps the serial port as the console, turns anti-lockout off and
limits the GUI's listeners to the LAN and the VLAN interfaces, replaces the sample's allow-all LAN rules with one rule admitting the operator
hosts to the GUI port, gives root a password and adds one
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
# Root's one-time password seed, in base32 as authenticator apps take it. A credentials file written before it
# existed holds the three above without it, and gets it appended.
OTP_SEED_NAME = "opnsense_root_otp_seed"
TOTP_SERVER_NAME = "TOTP"
# What the play, the scratch gateway's update and the diagnostics ask the API for, as the gateway's own privilege
# tables (ACL.xml) cover it. The firmware privilege covers the status check and the update alike.
API_PRIVILEGES = (
    "page-system-login-logout",  # api/diagnostics/system/system_information, the play's first call
    "page-system-firmware-manualupdate",  # api/core/firmware/*: the release check and the scratch update
    "page-firewall-alias-edit",  # api/firewall/alias/*
    "page-filter-api",  # api/firewall/filter/*
    "page-dhcp-kea-v4",  # api/kea/dhcpv4/* and api/kea/service/*
    "page-services-dnsforwarder",  # api/dnsmasq/*
    "page-services-unbound",  # api/unbound/*: the forwards
)
DEFAULT_CREDENTIALS = "~/.config/tofu/credentials.tfvars"
# The inventory's server_timezone, which a test pins this to.
DEFAULT_TIMEZONE = "Asia/Singapore"
# The only way onto the gateway before its first apply has written the guard rule: a legacy rule, which the API
# neither lists nor removes, so it stays until someone removes it in the GUI.
BOOTSTRAP_RULE_DESCRIPTION = "bootstrap: operator hosts to the GUI port on the untagged LAN"
MANAGEMENT_PORT = "443"
BASE = Path(__file__).with_name("config.xml.sample")
# One VLAN per block of 50 VMIDs (vlan_id = vmid // 50 * 5), each a /24 whose
# third octet is the tag and whose gateway address is .1. They are in ascending
# order, so the Nth smallest tag is interface optN. The gateway play's zones name
# their interfaces by that order, and 30 and 45 have no zone yet, so their
# interfaces carry none of its rules. VLAN 10 is the scratch gateways' WAN zone
# and sits first, so it is opt1 and every other zone is one further on.
WAN_ZONE_VLAN = 10
DEFAULT_VLANS = (10, 20, 25, 30, 35, 40, 45, 50, 55)
# A scratch gateway's WAN is leased from the WAN zone's /24, so its seed cannot carry VLAN 10 as an interface. A placeholder
# holds the interface's position, which keeps every other zone on the interface the play names. 11 is no block's tag
# (a multiple of 5), so no VM sits in it.
SCRATCH_PLACEHOLDER_VLAN = 11
SCRATCH_VLANS = tuple(SCRATCH_PLACEHOLDER_VLAN if tag == WAN_ZONE_VLAN else tag for tag in DEFAULT_VLANS)
VLAN_NAMESPACE = uuid.UUID("5d0c7a52-3c1e-4a53-9a0f-6a4a3f0f6a11")
ASSIGNMENT = re.compile(r'^\s*(\w+)\s*=\s*"([^"\\]*)"\s*(?:#.*)?$')


def crypt_sha512(clear: str) -> str:
    # The password goes in on stdin so it never shows in the process list.
    done = subprocess.run(["openssl", "passwd", "-6", "-stdin"], input=clear + "\n", capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SystemExit(f"openssl passwd failed: {done.stderr.strip()}")
    return done.stdout.strip()


def read_credentials(path: Path) -> dict[str, str]:
    """The seed's credentials as the file holds them; empty when it has none or does not exist."""
    if not path.exists():
        return {}
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise SystemExit(f"{path} is readable by others; chmod 600 it")
    found = {}
    for line in path.read_text().splitlines():
        m = ASSIGNMENT.match(line)
        if m and m[1] in (*CREDENTIAL_NAMES, OTP_SEED_NAME):
            found[m[1]] = m[2]
    return found


def new_otp_seed() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def append_assignments(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    separator = "" if existing.endswith("\n") or not existing else "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as fh:
        fh.write(separator + "".join(f'{name} = "{value}"\n' for name, value in values.items()))


def ensure_credentials(path: Path) -> dict[str, str]:
    """Return the credentials, appending generated ones to the file when it holds none of the first three.

    A file that holds the first three but no OTP seed gets a seed appended and keeps the rest.
    """
    found = read_credentials(path)
    if any(name in found for name in CREDENTIAL_NAMES):
        if not all(name in found for name in CREDENTIAL_NAMES):
            missing = ", ".join(n for n in CREDENTIAL_NAMES if n not in found)
            raise SystemExit(f"{path} holds some of the OPNsense credentials but not {missing}; set all three or none")
        if OTP_SEED_NAME not in found:
            found[OTP_SEED_NAME] = new_otp_seed()
            append_assignments(path, {OTP_SEED_NAME: found[OTP_SEED_NAME]})
        return found
    generated = {
        "opnsense_root_password": base64.urlsafe_b64encode(secrets.token_bytes(12)).decode(),
        "opnsense_api_key": base64.b64encode(secrets.token_bytes(60)).decode(),
        "opnsense_api_secret": base64.b64encode(secrets.token_bytes(60)).decode(),
        OTP_SEED_NAME: new_otp_seed(),
    }
    append_assignments(path, generated)
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
        set_text(vlan, "descr", f"VM ID {tag * 10}-{tag * 10 + 49}")
        set_text(vlan, "vlanif", f"vlan0.{tag}")
        opt = ET.SubElement(interfaces, f"opt{number}")
        set_text(opt, "if", f"vlan0.{tag}")
        set_text(opt, "descr", f"OPT{number}")
        set_text(opt, "enable", "1")
        set_text(opt, "ipaddr", f"192.168.{tag}.1")
        set_text(opt, "subnet", "24")
    root.insert(list(root).index(interfaces) + 1, vlans)


def add_bootstrap_rules(root: ET.Element, lan_ip: str, lan_prefix: str, operator_hosts: Sequence[str]) -> None:
    """Replace the sample's allow-all LAN rules with a pass rule per operator host, to the gateway's GUI port.

    Anti-lockout is off and the sample's rules are gone, so no other host on the untagged LAN reaches the
    management ports. The rule is on the LAN only: the zone interfaces are reached through the guard rule.
    """
    if not operator_hosts:
        raise SystemExit("name at least one operator host: a seed that admits nobody leaves only the console")
    lan_net = ipaddress.ip_network(f"{lan_ip}/{lan_prefix}", strict=False)
    for host in operator_hosts:
        try:
            address = ipaddress.IPv4Address(host)
        except ValueError:
            raise SystemExit(f"an operator host is an IPv4 address, got {host!r}") from None
        if address not in lan_net or address in (ipaddress.IPv4Address(lan_ip), lan_net.network_address, lan_net.broadcast_address):
            raise SystemExit(f"operator host {host} is not a host address on the LAN network {lan_net}")
    if len(set(operator_hosts)) != len(operator_hosts):
        raise SystemExit(f"an operator host is named twice: {list(operator_hosts)}")
    filter_el = root.find("filter")
    remove(filter_el, "rule")
    for host in operator_hosts:
        rule = ET.SubElement(filter_el, "rule")
        set_text(rule, "type", "pass")
        set_text(rule, "ipprotocol", "inet")
        set_text(rule, "descr", f"{BOOTSTRAP_RULE_DESCRIPTION} ({host})")
        set_text(rule, "interface", "lan")
        set_text(rule, "protocol", "tcp")
        set_text(ET.SubElement(rule, "source"), "address", host)
        destination = ET.SubElement(rule, "destination")
        set_text(destination, "network", "(self)")
        set_text(destination, "port", MANAGEMENT_PORT)


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
    operator_hosts: Sequence[str],
    timezone: str = DEFAULT_TIMEZONE,
    vlans: Sequence[int] = DEFAULT_VLANS,
) -> ET.ElementTree:
    tree = ET.parse(base)  # noqa: S314 - the sample configuration shipped beside this script
    root = tree.getroot()
    system = root.find("system")

    set_text(system, "hostname", hostname)
    set_text(system, "domain", domain)
    set_text(system, "timezone", timezone)

    # Root keeps its group and uid; only the password changes.
    for user in system.findall("user"):
        if user.findtext("name") == "root":
            set_text(user, "password", crypt_sha512(creds["opnsense_root_password"]))
            set_text(user, "otp_seed", creds[OTP_SEED_NAME])

    api = ET.Element("user")
    set_text(api, "name", api_user)
    set_text(api, "descr", "API user of the configuration play")
    set_text(api, "scope", "user")
    # The account cannot log in: its password is a hash of random bytes.
    set_text(api, "password", crypt_sha512(base64.b64encode(secrets.token_bytes(32)).decode()))
    set_text(api, "uid", "2000")
    for privilege in API_PRIVILEGES:
        ET.SubElement(api, "priv").text = privilege
    item = ET.SubElement(ET.SubElement(api, "apikeys"), "item")
    set_text(item, "key", creds["opnsense_api_key"])
    set_text(item, "secret", crypt_sha512(creds["opnsense_api_secret"]))
    # Users sit after the groups, before the remaining system settings.
    users = system.findall("user")
    system.insert(list(system).index(users[-1]) + 1, api)
    set_text(system, "nextuid", "2001")

    # The GUI asks for root's password with a one-time password in front of it. OPNsense has no way left to keep
    # the console off that rule, so the console menu is not password-protected: whoever can open the VM's console
    # in Proxmox reaches it, and it is the way in when the token is lost. The API user authenticates by key.
    remove(system, "disableconsolemenu")
    server = ET.Element("authserver")
    set_text(server, "refid", uuid.uuid5(VLAN_NAMESPACE, "authserver-totp").hex[:13])
    set_text(server, "type", "totp")
    set_text(server, "name", TOTP_SERVER_NAME)
    set_text(server, "otpLength", "6")
    system.insert(list(system).index(api) + 1, server)
    set_text(system.find("webgui"), "authmode", TOTP_SERVER_NAME)

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

    # Management reach: the GUI and API listen on the LAN and the VLAN interfaces only (never the WAN), the gateway
    # admits no host to them by default, and the guard rule and the bootstrap rule below are the only admissions.
    webgui = system.find("webgui")
    set_text(webgui, "noantilockout", "1")
    set_text(webgui, "interfaces", ",".join(["lan", *(f"opt{n}" for n in range(1, len(vlans) + 1))]))
    add_bootstrap_rules(root, lan_ip, lan_prefix, operator_hosts)

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
    vlan_list = ap.add_mutually_exclusive_group()
    vlan_list.add_argument("--vlans", default=",".join(map(str, DEFAULT_VLANS)), help="comma-separated VLAN tags to add on the LAN device, none when empty")
    vlan_list.add_argument(
        "--scratch",
        action="store_true",
        help=(
            f"add the scratch gateway's VLANs ({','.join(map(str, SCRATCH_VLANS))}): "
            f"the default list with {SCRATCH_PLACEHOLDER_VLAN} in place of {WAN_ZONE_VLAN}"
        ),
    )
    ap.add_argument("--hostname", default="OPNsense")
    ap.add_argument("--domain", default="internal", help="with the hostname, the management name the play verifies the GUI certificate for")
    ap.add_argument("--api-user", default="ansible")
    ap.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="the gateway's time zone")
    ap.add_argument(
        "--operator-host",
        action="append",
        required=True,
        dest="operator_hosts",
        help="an address on the LAN network that may reach the GUI port before the play's first apply; repeat for each",
    )
    ap.add_argument("--wan-dhcp-hostname", help="the name the WAN's DHCP lease is registered under; the sample's empty value when omitted")
    a = ap.parse_args(argv)

    try:
        vlans = list(SCRATCH_VLANS) if a.scratch else [int(tag) for tag in a.vlans.split(",") if tag.strip()]
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
        operator_hosts=a.operator_hosts,
        timezone=a.timezone,
        vlans=vlans,
    )
    tree.write(a.out, encoding="UTF-8", xml_declaration=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
