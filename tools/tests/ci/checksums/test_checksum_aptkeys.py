"""Tests for ci.checksums.aptkeys, with real gpg and keys generated per test.

The vendor is a function that returns bytes. Nothing here reaches a real vendor;
a run against the real ones is the workflow's.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import gpg_keys
import pytest
import yaml
from ci.checksums import aptkeys
from ci.checksums.registry import Location
from ci.checksums.verify import FetchError

REPO_ROOT = Path(__file__).resolve().parents[4]
PIN_FILE = "defaults.yaml"
URL = "https://vendor.invalid/key.gpg"


def key_for(name: str = "vendor") -> aptkeys.AptKey:
    return aptkeys.AptKey(name, URL, Location(PIN_FILE, "vendor_apt_key_fingerprint"))


def tree(root: Path, pin: str) -> Path:
    (root / PIN_FILE).write_text(f"---\nvendor_apt_key_fingerprint: {pin}\n")
    return root


def serving(body: bytes):
    def fetch(url: str) -> bytes:
        assert url == URL
        return body

    return fetch


def failure(outcome: aptkeys.Outcome) -> str:
    assert len(outcome.errors) == 1
    return outcome.errors[0]


SAMPLES = [
    "pub:-:2048:1:08958DCF2CE44379:1793702244:::-:::scESC::::::23::0:\nfpr:::::::::AE623D99072E9AC03986184308958DCF2CE44379:\nsub:-:2048:1:4F58E9D28076F0F8:1793702244::::::e::::::23:\nfpr:::::::::806D48797728514C9D2B9A944F58E9D28076F0F8:\n",
    "pub:-:2048:1:A:1::::::::::\nfpr:::::::::AAAA:\npub:-:2048:1:B:1::::::::::\nfpr:::::::::BBBB:\n",
    "sec:u:2048:1:E16763323BBEEE75:1793702265:::u:::scSC:::+:::23::0:\nfpr:::::::::4DE93B3B3F90D0F84DCEAE86E16763323BBEEE75:\n",
    "fpr:::::::::AAAA:\n",
    "",
]


class TestPrimaryFingerprints:
    @pytest.mark.parametrize("colons", SAMPLES, ids=["a primary key with a subkey", "two keys", "a secret key", "an fpr with no key", "nothing"])
    def test_it_lists_what_the_ansible_filter_the_roles_use_lists(self, colons):
        assert aptkeys.primary_fingerprints(colons) == gpg_keys.gpg_primary_fingerprints(colons)

    def test_an_fpr_record_without_a_fingerprint_is_an_error(self):
        with pytest.raises(ValueError, match="no fingerprint"):
            aptkeys.primary_fingerprints("pub:-:2048:1:A:1::::::::::\nfpr:\n")


class TestCheckKey:
    def test_the_pinned_key_passes(self, tmp_path, signer):
        outcome = aptkeys.check_key(tree(tmp_path, signer.fingerprint), key_for(), serving(signer.public_key()))

        assert outcome.ok

    def test_a_different_key_fails_naming_both_fingerprints(self, tmp_path, make_signer):
        pinned, served = make_signer("Pinned"), make_signer("Served")

        message = failure(aptkeys.check_key(tree(tmp_path, pinned.fingerprint), key_for(), serving(served.public_key())))

        assert served.fingerprint in message
        assert pinned.fingerprint in message

    def test_the_pinned_key_with_a_second_one_fails(self, tmp_path, make_signer):
        pinned, extra = make_signer("Pinned"), make_signer("Extra")

        message = failure(aptkeys.check_key(tree(tmp_path, pinned.fingerprint), key_for(), serving(pinned.public_key() + extra.public_key())))

        assert extra.fingerprint in message

    def test_an_unreachable_vendor_fails(self, tmp_path, signer):
        def down(url: str) -> bytes:
            raise FetchError(f"{url}: HTTP 503 after 3 attempts")

        assert "HTTP 503" in failure(aptkeys.check_key(tree(tmp_path, signer.fingerprint), key_for(), down))

    def test_a_download_that_is_not_a_key_fails(self, tmp_path, signer):
        assert "can't read the key" in failure(aptkeys.check_key(tree(tmp_path, signer.fingerprint), key_for(), serving(b"<html>blocked</html>")))

    @pytest.mark.parametrize(
        "pin", ["9dc858229fc7dd38854ae2d88d81803c0ebfcd88", "9DC8 5822 9FC7 DD38", "9DC858229FC7DD38"], ids=["lower case", "spaced", "short"]
    )
    def test_a_pin_that_is_not_a_plain_upper_case_fingerprint_fails(self, tmp_path, signer, pin):
        outcome = aptkeys.check_key(tree(tmp_path, pin), key_for(), serving(signer.public_key()))

        assert not outcome.ok

    def test_a_missing_pin_fails(self, tmp_path, signer):
        (tmp_path / PIN_FILE).write_text("---\nother: 1\n")

        assert "has no vendor_apt_key_fingerprint" in failure(aptkeys.check_key(tmp_path, key_for(), serving(signer.public_key())))

    def test_a_runner_without_gpg_fails_instead_of_passing(self, tmp_path, signer):
        def no_gpg(args, cwd, capture):
            raise FileNotFoundError("gpg")

        outcome = aptkeys.check_key(tree(tmp_path, signer.fingerprint), key_for(), serving(signer.public_key()), no_gpg)

        assert failure(outcome) == "gpg is not installed"

    def test_gpg_leaves_nothing_behind(self, tmp_path, signer):
        homes: list[Path] = []
        real = aptkeys.proc.run

        def spy(args, cwd, capture=False):
            homes.append(cwd)
            return real(args, cwd, capture)

        aptkeys.check_key(tree(tmp_path, signer.fingerprint), key_for(), serving(signer.public_key()), spy)

        assert homes
        assert not homes[0].exists()


class TestMain:
    class Vendor:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def fetch(self, url: str) -> bytes:
            return self.body

    def test_it_exits_zero_when_every_key_matches(self, tmp_path, signer, capsys):
        code = aptkeys.main([], tree(tmp_path, signer.fingerprint), (key_for(),), self.Vendor(signer.public_key()))

        assert code == 0
        assert "1 apt keys: 1 passed, 0 failed (vendor)" in capsys.readouterr().out

    def test_it_exits_one_and_annotates_a_mismatch(self, tmp_path, make_signer, capsys):
        code = aptkeys.main([], tree(tmp_path, make_signer("A").fingerprint), (key_for(),), self.Vendor(make_signer("B").public_key()))

        out = capsys.readouterr().out
        assert code == 1
        assert re.search(rf"::error::vendor \({PIN_FILE}\): ", out)
        assert "vendor FAILED" in out

    def test_it_checks_only_the_keys_it_is_asked_for(self, tmp_path, signer):
        keys = (key_for("one"), key_for("two"))

        class Counting(self.Vendor):
            asked = 0

            def fetch(self, url: str) -> bytes:
                Counting.asked += 1
                return super().fetch(url)

        aptkeys.main(["two"], tree(tmp_path, signer.fingerprint), keys, Counting(signer.public_key()))

        assert Counting.asked == 1

    def test_an_unknown_key_name_is_refused(self, tmp_path, signer):
        with pytest.raises(SystemExit) as exit_info:
            aptkeys.main(["nope"], tree(tmp_path, signer.fingerprint), (key_for(),), self.Vendor(b""))

        assert exit_info.value.code == 2


class TestRegistry:
    def role_pins(self) -> dict[str, str]:
        found = {}
        for defaults in sorted((REPO_ROOT / "ansible/roles").glob("*/defaults/main.yaml")):
            for name in yaml.safe_load(defaults.read_text()) or {}:
                if name.endswith("_apt_key_fingerprint"):
                    found[name] = defaults.relative_to(REPO_ROOT).as_posix()
        return found

    def test_every_apt_key_pin_in_a_role_has_an_entry(self):
        registered = {(key.pin.path, key.pin.name) for key in aptkeys.KEYS}

        assert {(path, name) for name, path in self.role_pins().items()} == registered

    @pytest.mark.parametrize("key", aptkeys.KEYS, ids=lambda key: key.name)
    def test_each_entrys_pin_is_a_readable_full_fingerprint(self, key):
        assert aptkeys.FINGERPRINT.fullmatch(aptkeys.pins.read_value(REPO_ROOT, key.pin))

    @pytest.mark.parametrize("key", aptkeys.KEYS, ids=lambda key: key.name)
    def test_each_entrys_address_is_the_one_its_role_downloads_from(self, key):
        role = key.pin.path.split("/")[2]
        urls = []
        for tasks_file in sorted((REPO_ROOT / "ansible/roles" / role / "tasks").glob("*.yaml")):
            for task in yaml.safe_load(tasks_file.read_text()) or []:
                if "ansible.builtin.get_url" in task:
                    urls.append(task["ansible.builtin.get_url"]["url"].replace("{{ ansible_facts['distribution_release'] }}", "resolute"))

        assert key.url in urls

    def test_the_entries_are_named_once(self):
        names = [key.name for key in aptkeys.KEYS]

        assert len(names) == len(set(names))

    def test_gpg_is_available_for_the_checks_above(self):
        assert subprocess.run(["gpg", "--version"], capture_output=True, check=False).returncode == 0
