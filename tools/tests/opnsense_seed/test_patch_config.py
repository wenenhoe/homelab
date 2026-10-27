"""Tests for the seed configuration builder of the OPNsense module."""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import patch_config
import pytest

CREDENTIAL_NAMES = ("opnsense_root_password", "opnsense_api_key", "opnsense_api_secret")
CREDS = {"opnsense_root_password": "root-pw-123", "opnsense_api_key": "KEY+/abc=", "opnsense_api_secret": "SECRET+/xyz="}
OPTIONS = {
    "wan_if": "vtnet0",
    "lan_if": "vtnet1",
    "lan_ip": "192.168.77.1",
    "lan_prefix": "24",
    "hostname": "OPNsense",
    "domain": "internal",
    "api_user": "ansible",
    "wan_dhcp_hostname": None,
}


@pytest.fixture
def credentials_path(tmp_path_factory) -> Path:
    """A path in a directory of its own, where the file does not exist yet."""
    return tmp_path_factory.mktemp("tofu") / "credentials.tfvars"


def write_credentials(path: Path, text: str, mode: int = 0o600) -> Path:
    path.write_text(text)
    path.chmod(mode)
    return path


def assignments(names=CREDENTIAL_NAMES) -> str:
    return "".join(f'{name} = "{CREDS[name]}"\n' for name in names)


def seed(**overrides) -> ET.Element:
    return patch_config.build_seed(patch_config.BASE, CREDS, **{**OPTIONS, **overrides}).getroot()


def crypt_matches(clear: str, crypted: str) -> bool:
    """Whether `crypted` is the SHA-512 crypt of `clear`, by hashing again with the salt it carries."""
    algorithm, salt = crypted.split("$")[1:3]
    assert algorithm == "6"
    again = subprocess.run(["openssl", "passwd", "-6", "-salt", salt, "-stdin"], input=clear + "\n", capture_output=True, text=True, check=True)
    return again.stdout.strip() == crypted


def api_user(root: ET.Element, name: str = "ansible") -> ET.Element:
    return next(u for u in root.find("system").findall("user") if u.findtext("name") == name)


class TestBuildSeed:
    def test_assigns_the_devices_and_the_lan_address(self):
        interfaces = seed(wan_if="vtnet2", lan_if="vtnet3", lan_ip="10.9.8.1", lan_prefix="16").find("interfaces")

        assert [interfaces.findtext("wan/if"), interfaces.findtext("lan/if")] == ["vtnet2", "vtnet3"]
        assert [interfaces.findtext("lan/ipaddr"), interfaces.findtext("lan/subnet")] == ["10.9.8.1", "16"]

    def test_names_the_gateway_by_its_management_name(self):
        system = seed(hostname="gw", domain="lab.internal").find("system")

        assert [system.findtext("hostname"), system.findtext("domain")] == ["gw", "lab.internal"]

    def test_keeps_the_serial_port_as_the_console(self):
        system = seed().find("system")

        assert [system.findtext(tag) for tag in ("primaryconsole", "secondaryconsole", "serialspeed")] == ["serial", "video", "115200"]

    def test_stores_the_root_password_as_a_hash_of_the_credential(self):
        root_user = next(u for u in seed().find("system").findall("user") if u.findtext("name") == "root")

        assert crypt_matches(CREDS["opnsense_root_password"], root_user.findtext("password"))
        assert root_user.findtext("uid") == "0"

    def test_adds_an_api_user_whose_key_is_the_credential_and_whose_secret_is_its_hash(self):
        item = api_user(seed()).find("apikeys/item")

        assert item.findtext("key") == CREDS["opnsense_api_key"]
        assert crypt_matches(CREDS["opnsense_api_secret"], item.findtext("secret"))

    def test_the_api_user_cannot_log_in_with_any_known_password(self):
        user = api_user(seed(api_user="svc-play"), "svc-play")

        assert not any(crypt_matches(clear, user.findtext("password")) for clear in CREDS.values())

    def test_places_the_api_user_after_the_other_users_and_advances_the_uid_counter(self):
        root = seed()
        system = root.find("system")

        assert [child.findtext("name") for child in system if child.tag == "user"] == ["root", "ansible"]
        assert [system.findtext("nextuid"), api_user(root).findtext("uid")] == ["2001", "2000"]

    def test_carries_the_root_password_and_the_api_secret_only_as_hashes(self):
        text = ET.tostring(seed(), encoding="unicode")

        assert CREDS["opnsense_root_password"] not in text
        assert CREDS["opnsense_api_secret"] not in text

    @pytest.mark.parametrize(
        ("name", "expected"),
        [pytest.param(None, "", id="left-as-the-sample-has-it"), pytest.param("opn-lab", "opn-lab", id="set")],
    )
    def test_registers_the_wan_lease_name_only_when_asked(self, name, expected):
        assert (seed(wan_dhcp_hostname=name).findtext("interfaces/wan/dhcphostname") or "") == expected


class TestEnsureCredentials:
    def test_returns_the_values_a_file_already_holds_and_leaves_it_alone(self, credentials_path):
        text = f'proxmox_endpoint = "https://pve:8006/"\n{assignments()}'
        write_credentials(credentials_path, text)

        assert patch_config.ensure_credentials(credentials_path) == CREDS
        assert credentials_path.read_text() == text

    def test_generates_all_three_into_a_new_file_readable_by_its_owner_only(self, credentials_path):
        generated = patch_config.ensure_credentials(credentials_path)

        assert set(generated) == set(CREDENTIAL_NAMES)
        assert patch_config.read_credentials(credentials_path) == generated
        assert oct(credentials_path.stat().st_mode & 0o777) == "0o600"

    def test_creates_the_directory_closed_to_others(self, credentials_path, tmp_path_factory):
        nested = tmp_path_factory.mktemp("home") / "tofu" / "credentials.tfvars"

        patch_config.ensure_credentials(nested)

        assert oct(nested.parent.stat().st_mode & 0o777) == "0o700"

    def test_generates_a_different_secret_for_each_credential(self, credentials_path):
        generated = patch_config.ensure_credentials(credentials_path)

        assert len(set(generated.values())) == 3

    @pytest.mark.parametrize(
        "existing",
        [
            pytest.param('proxmox_endpoint = "https://pve:8006/"\n', id="newline-ended"),
            pytest.param('proxmox_endpoint = "https://pve:8006/"', id="no-final-newline"),
        ],
    )
    def test_appends_to_a_file_with_other_settings_and_keeps_them(self, credentials_path, existing):
        write_credentials(credentials_path, existing)

        generated = patch_config.ensure_credentials(credentials_path)

        lines = credentials_path.read_text().splitlines()
        assert lines[0] == 'proxmox_endpoint = "https://pve:8006/"'
        assert len(lines) == 4
        assert patch_config.read_credentials(credentials_path) == generated

    def test_a_second_call_returns_what_the_first_generated(self, credentials_path):
        first = patch_config.ensure_credentials(credentials_path)

        assert patch_config.ensure_credentials(credentials_path) == first

    def test_refuses_a_file_that_holds_only_some_of_them(self, credentials_path):
        write_credentials(credentials_path, assignments(CREDENTIAL_NAMES[:2]))

        with pytest.raises(SystemExit, match="opnsense_api_secret"):
            patch_config.ensure_credentials(credentials_path)

        assert credentials_path.read_text() == assignments(CREDENTIAL_NAMES[:2])

    def test_refuses_a_file_others_can_read(self, credentials_path):
        write_credentials(credentials_path, assignments(), mode=0o644)

        with pytest.raises(SystemExit, match="chmod 600"):
            patch_config.ensure_credentials(credentials_path)

    def test_ignores_a_commented_assignment(self, credentials_path):
        write_credentials(credentials_path, f"# {assignments(CREDENTIAL_NAMES[:1])}")

        assert set(patch_config.ensure_credentials(credentials_path)) == set(CREDENTIAL_NAMES)


class TestMain:
    def test_writes_a_seed_with_the_credentials_of_the_file(self, credentials_path, tmp_path_factory):
        write_credentials(credentials_path, assignments())
        out = tmp_path_factory.mktemp("out") / "config.xml"

        assert patch_config.main(["--out", str(out), "--credentials", str(credentials_path), "--lan-ip", "192.168.77.1"]) == 0

        written = ET.parse(out).getroot()  # noqa: S314 - the file this test just wrote
        assert api_user(written).findtext("apikeys/item/key") == CREDS["opnsense_api_key"]

    def test_a_lan_address_is_required(self, credentials_path, tmp_path_factory, capsys):
        out = tmp_path_factory.mktemp("out") / "config.xml"

        with pytest.raises(SystemExit) as stopped:
            patch_config.main(["--out", str(out), "--credentials", str(credentials_path)])

        assert stopped.value.code == 2
        assert "--lan-ip" in capsys.readouterr().err
        assert not out.exists()
