"""Tests for the first-boot importer driver, run against a stand-in for the VM's serial socket."""

from __future__ import annotations

import hashlib
import io
import json
import ssl
import subprocess
import sys
from pathlib import Path

import import_seed
import pytest
from _fake_console import FakeConsole

SEED_PASSWORD = "seedpw-123"


def make_certificate(directory: Path, name: str) -> str:
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(directory / f"{name}.key"),
            "-out", str(directory / f"{name}.pem"), "-days", "397", "-subj", f"/CN={name}", "-addext", f"subjectAltName=DNS:{name}",
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return (directory / f"{name}.pem").read_text()


@pytest.fixture(scope="session")
def certificates(tmp_path_factory) -> dict[str, str]:
    directory = tmp_path_factory.mktemp("certs")
    return {name: make_certificate(directory, name) for name in ("OPNsense.internal", "other.internal")}


@pytest.fixture
def work(tmp_path_factory) -> Path:
    """A short directory for the socket (a unix socket path is limited to 108 bytes) and the driver's output."""
    return tmp_path_factory.mktemp("w")


@pytest.fixture
def drive(work, certificates, monkeypatch):
    """Run the driver against a fake console with the given fault; returns (exit status, result dict, fake)."""
    consoles = []

    def run(fault=None, *, banner_pem=None, password=SEED_PASSWORD, extra=()):
        console = FakeConsole(work / "s", certificates["OPNsense.internal"], seed_password=SEED_PASSWORD, banner_pem=banner_pem, fault=fault)
        consoles.append(console)
        monkeypatch.setattr(sys, "stdin", io.StringIO(f"{password}\n"))
        argv = [
            "--socket", str(work / "s"), "--log", str(work / "console.log"), "--result", str(work / "result.json"),
            "--cert-out", str(work / "gateway-cert.pem"), "--boot-timeout", "5", "--step-timeout", "4", "--nudge-quiet", "0.5",
            "--poll-interval", "0.01", *extra,
        ]  # fmt: skip
        status = import_seed.main(argv)
        return status, json.loads((work / "result.json").read_text()), console

    yield run
    for console in consoles:
        console.close()


def fingerprint(pem: str) -> str:
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


class TestSeeding:
    def test_answers_the_importer_and_logs_in_with_the_seed_password(self, drive):
        status, result, console = drive()

        assert status == 0
        assert result["result"] == "done"
        assert result["restored"] is True
        assert console.typed_at_password == list(SEED_PASSWORD)

    def test_writes_the_certificate_the_gui_serves(self, drive, work, certificates):
        status, result, _ = drive()

        assert status == 0
        assert (work / "gateway-cert.pem").read_text() == certificates["OPNsense.internal"]
        assert result["cert_sha256"] == fingerprint(certificates["OPNsense.internal"])

    def test_the_console_banner_agrees_with_the_certificate(self, drive):
        _, result, _ = drive()

        assert result["banner_matches_cert"] is True

    def test_the_transcript_does_not_hold_the_password(self, drive, work):
        drive()

        assert SEED_PASSWORD not in (work / "console.log").read_text(errors="replace")

    def test_starting_inside_a_root_shell_still_reaches_the_menu(self, drive):
        status, result, _ = drive("shellstart")

        assert (status, result["result"]) == (0, "done")

    def test_names_the_seed_disk_it_was_given(self, drive):
        status, result, _ = drive(extra=["--seed-disk", "da1"])

        assert (status, result["restored"]) == (0, True)

    def test_a_seed_on_another_disk_is_not_restored(self, drive, work):
        status, result, _ = drive(extra=["--seed-disk", "da2"])

        assert (status, result) == (3, {"restored": False, "result": "seed did not land"})
        assert not (work / "gateway-cert.pem").exists()


class TestFailures:
    def test_an_importer_that_finds_no_disk_stops_before_any_login(self, drive, work):
        status, result, console = drive("wrongdisk")

        assert status == 3
        assert result["restored"] is False
        assert console.typed_at_password == []
        assert not (work / "gateway-cert.pem").exists()

    def test_a_first_boot_without_the_importer_times_out_naming_the_step(self, drive, capsys):
        status, result, _ = drive("noimporter", extra=["--boot-timeout", "1"])

        assert status == 2
        assert "importer prompt on the first boot" in result["detail"]
        assert "last output" in capsys.readouterr().err

    def test_a_refused_password_is_reported_and_not_retried(self, drive):
        status, result, console = drive("badpw")

        assert (status, result["result"]) == (4, "login refused")
        assert console.typed_at_password == list(SEED_PASSWORD)

    def test_a_wrong_password_on_stdin_is_refused(self, drive):
        status, result, _ = drive(password="not-the-password")

        assert (status, result["result"]) == (4, "login refused")

    def test_a_certificate_that_never_appears_is_an_error_and_writes_no_file(self, drive, work):
        status, result, _ = drive("nocert")

        assert (status, result["result"], result["cert_sha256"]) == (5, "certificate not read", None)
        assert not (work / "gateway-cert.pem").exists()

    def test_a_banner_for_another_certificate_is_an_error_and_writes_no_file(self, drive, work, certificates):
        status, result, _ = drive(banner_pem=certificates["other.internal"])

        assert (status, result["banner_matches_cert"]) == (5, False)
        assert not (work / "gateway-cert.pem").exists()

    def test_a_banner_without_a_fingerprint_does_not_stop_the_read(self, drive):
        status, result, _ = drive("nobanner")

        assert (status, result["banner_matches_cert"]) == (0, None)

    def test_a_missing_serial_socket_is_a_timeout(self, work, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO(f"{SEED_PASSWORD}\n"))

        status = import_seed.main(["--socket", str(work / "none"), "--log", str(work / "l"), "--result", str(work / "r.json"), "--connect-timeout", "0.3"])

        assert status == 2
        assert "did not appear" in capsys.readouterr().err


class TestPassword:
    def test_an_empty_stdin_is_refused_before_the_console_is_touched(self, work, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))

        with pytest.raises(SystemExit) as stopped:
            import_seed.main(["--socket", str(work / "s")])

        assert stopped.value.code == 2
        assert "first line of stdin" in capsys.readouterr().err
