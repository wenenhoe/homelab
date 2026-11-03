"""Unit tests for rebuild_check.known_hosts. known_hosts files are real; `ssh-keygen` is replaced by a stand-in that edits them."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from unittest.mock import create_autospec

import paramiko
import pytest
from rebuild_check import known_hosts

HOST = "play"
FQDN = "play.internal.example.com"
ADDRESS = "192.168.20.4"
ENTRIES = [HOST, FQDN, ADDRESS]


def key_line(hostnames: str) -> str:
    key = paramiko.ECDSAKey.generate()
    return f"{hostnames} {key.get_name()} {key.get_base64()}\n"


def hashed_line(hostname: str) -> str:
    """A line as `HashKnownHosts yes` writes it: |1|salt|hash in place of the name."""
    hashed = paramiko.HostKeys.hash_host(hostname)
    return key_line(hashed)


def lines_for(path: Path) -> list[str]:
    return path.read_text().splitlines()


def fake_ssh_keygen(drops_nothing: bool = False):
    """Stands in for `ssh-keygen -R NAME -f FILE`: drops the lines that carry NAME, plain or hashed."""

    def run(argv, **_kwargs):
        _, _, name, _, filename = argv
        path = Path(filename)
        kept = []
        for line in path.read_text().splitlines(keepends=True):
            field = line.split()[0]
            hashed = field.startswith("|1|") and paramiko.HostKeys.hash_host(name, field.split("|")[2]) == field
            carries = hashed or name in field.split(",")
            if drops_nothing or not carries:
                kept.append(line)
        path.write_text("".join(kept))
        return subprocess.CompletedProcess(argv, 0, stdout=f"# Host {name} found\n", stderr="")

    return create_autospec(subprocess.run, side_effect=run)


@pytest.fixture
def known_hosts_file(tmp_path: Path) -> Path:
    path = tmp_path / "known_hosts"
    path.write_text(key_line(f"{HOST},{ADDRESS}") + key_line(FQDN) + hashed_line(FQDN) + key_line("storage.internal.example.com,192.168.20.6"))
    return path


class TestEntries:
    def test_the_short_name_the_fqdn_and_the_address_dns_gives(self, secrets_dir):
        secrets_dir.seed("main-domain", "example.com")

        assert known_hosts.entries_for(HOST, resolve=create_autospec(lambda name: "", return_value=ADDRESS)) == ENTRIES

    def test_a_name_that_does_not_resolve_stops_before_anything_is_removed(self, secrets_dir):
        secrets_dir.seed("main-domain", "example.com")

        def refuses(_name: str) -> str:
            raise OSError("Name or service not known")

        with pytest.raises(SystemExit, match=re.escape(f"{FQDN} does not resolve from here")):
            known_hosts.entries_for(HOST, resolve=refuses)


class TestRemaining:
    def test_plain_and_hashed_entries_are_found_and_another_host_is_not(self, known_hosts_file):
        assert known_hosts.remaining(known_hosts_file, [*ENTRIES, "services"]) == ENTRIES


class TestRemove:
    def test_every_entry_goes_plain_and_hashed_and_another_hosts_line_stays(self, known_hosts_file):
        run = fake_ssh_keygen()

        left = known_hosts.remove(known_hosts_file, ENTRIES, run=run)

        assert left == []
        assert [line.split()[0] for line in lines_for(known_hosts_file)] == ["storage.internal.example.com,192.168.20.6"]
        assert [call.args[0] for call in run.call_args_list] == [["ssh-keygen", "-R", entry, "-f", str(known_hosts_file)] for entry in ENTRIES]

    def test_an_entry_ssh_keygen_left_behind_is_reported(self, known_hosts_file):
        left = known_hosts.remove(known_hosts_file, ENTRIES, run=fake_ssh_keygen(drops_nothing=True))

        assert left == ENTRIES

    def test_what_ssh_keygen_says_is_printed_with_the_entry(self, known_hosts_file, capsys):
        known_hosts.remove(known_hosts_file, [HOST], run=fake_ssh_keygen())

        assert capsys.readouterr().out == "play: # Host play found\n"


class TestMain:
    def test_a_clean_run_exits_0_and_says_nothing_remains(self, known_hosts_file, secrets_dir, monkeypatch, capsys):
        secrets_dir.seed("main-domain", "example.com")
        monkeypatch.setattr(known_hosts, "entries_for", create_autospec(known_hosts.entries_for, return_value=ENTRIES))
        monkeypatch.setattr(subprocess, "run", fake_ssh_keygen())

        status = known_hosts.main([HOST, "--known-hosts", str(known_hosts_file)])

        assert status == 0
        assert f"no entry for play remains in {known_hosts_file}" in capsys.readouterr().out

    def test_an_entry_that_remains_exits_1_and_names_it(self, known_hosts_file, monkeypatch, capsys):
        monkeypatch.setattr(known_hosts, "entries_for", create_autospec(known_hosts.entries_for, return_value=ENTRIES))
        monkeypatch.setattr(subprocess, "run", fake_ssh_keygen(drops_nothing=True))

        status = known_hosts.main([HOST, "--known-hosts", str(known_hosts_file)])

        assert status == 1
        assert f"still in {known_hosts_file}: play, {FQDN}, {ADDRESS}" in capsys.readouterr().err

    def test_a_missing_file_has_nothing_to_remove(self, tmp_path, capsys):
        missing = tmp_path / "absent"

        assert known_hosts.main([HOST, "--known-hosts", str(missing)]) == 0
        assert "does not exist: nothing to remove" in capsys.readouterr().out
