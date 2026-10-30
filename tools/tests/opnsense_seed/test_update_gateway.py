"""Tests for update_gateway.sh, run against a stand-in for the gateway's HTTPS API."""

from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest
from _fake_api import FakeApi
from _fake_console import FakeConsole

SCRIPT = Path(__file__).resolve().parents[3] / "tofu" / "scratch" / "opnsense" / "update_gateway.sh"
KEY, SECRET = "KEYKEYKEYKEY", "SECRETSECRET"


@pytest.fixture(scope="module")
def certificate(tmp_path_factory) -> tuple[str, str]:
    directory = tmp_path_factory.mktemp("cert")
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(directory / "key.pem"),
            "-out", str(directory / "cert.pem"), "-days", "30", "-subj", "/CN=OPNsense.internal", "-addext", "subjectAltName=DNS:OPNsense.internal",
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return str(directory / "cert.pem"), str(directory / "key.pem")


@pytest.fixture
def update(certificate, tmp_path):
    """Run the script against a fake API with the given fault; returns (exit status, output, fake API)."""
    creds = tmp_path / "gateway.env"
    creds.write_text(f"API_KEY='{KEY}'\nAPI_SECRET='{SECRET}'\nLAN_IP='192.168.77.1'\n")

    def run(fault="", *, version="26.1.6_2", env=None):
        with FakeApi(*certificate, f"{KEY}:{SECRET}", fault=fault, version=version) as api:
            environment = {
                **os.environ,
                "GW_IP": "127.0.0.1",
                "GW_PORT": str(api.port),
                "POLL": "0.2",
                "UPDATE_TIMEOUT": "25",
                "UP_TIMEOUT": "20",
                **(env or {}),
            }
            done = subprocess.run(
                ["bash", str(SCRIPT), str(creds), certificate[0], "26.1.11", str(tmp_path / "out")],
                env=environment, capture_output=True, text=True, check=False, timeout=120,
            )  # fmt: skip
        return done.returncode, done.stdout + done.stderr, api

    return run


def updated(api: FakeApi) -> bool:
    return "POST /api/core/firmware/update" in api.calls


def test_update_with_a_reboot_lands_on_the_pin_and_keeps_the_seeded_key(update):
    status, output, api = update()
    assert status == 0, output
    assert updated(api)
    assert "CHECK the gateway went down for the reboot: PASS" in output
    assert "CHECK the gateway runs 26.1.11 after the update: PASS" in output
    assert "CHECK the seed's seeded API user works after the update: PASS" in output


def test_update_that_ends_without_a_reboot_passes(update):
    status, output, _ = update("noreboot")
    assert status == 0, output
    assert "CHECK the gateway runs 26.1.11 after the update: PASS" in output


def test_a_gateway_already_on_the_pin_is_not_updated(update):
    status, output, api = update(version="26.1.11_10")
    assert status == 0, output
    assert not updated(api)
    assert "already at 26.1.11" in output


def test_an_update_that_would_pass_the_pin_is_refused_and_never_started(update):
    status, output, api = update("latest-differs")
    assert status != 0
    assert "CHECK the update lands on the pinned 26.1.11: FAIL" in output
    assert not updated(api)


def test_allow_latest_updates_anyway_and_still_reports_missing_the_pin(update):
    status, output, api = update("latest-differs", env={"ALLOW_LATEST": "1"})
    assert status != 0
    assert updated(api)
    assert "CHECK the gateway runs 26.1.11 after the update: FAIL" in output


def test_an_unreachable_mirror_fails(update):
    status, output, api = update("nomirror")
    assert status != 0
    assert "CHECK the gateway reaches its update mirror: FAIL" in output
    assert not updated(api)


def test_an_update_that_leaves_the_version_unchanged_fails(update):
    status, output, _ = update("badversion")
    assert status != 0
    assert "CHECK the gateway runs 26.1.11 after the update: FAIL" in output


def test_a_key_refused_after_the_update_fails(update):
    status, output, _ = update("keylost", env={"UP_TIMEOUT": "4"})
    assert status != 0
    assert "CHECK the API answers again after the update: FAIL" in output


def test_a_wrong_secret_accepted_after_the_update_fails(update):
    status, output, _ = update("authopen")
    assert status != 0
    assert "CHECK the seed's seeded API user works after the update: FAIL" in output


def test_an_update_job_that_never_ends_fails(update):
    status, output, _ = update("stuck", env={"UPDATE_TIMEOUT": "4"})
    assert status != 0
    assert "CHECK the update job finished: FAIL" in output


CHECK = "CHECK the serial console shows a login prompt or the menu after the reboot"


@pytest.fixture
def console(certificate, tmp_path):
    """Serve a stand-in serial console on a short socket path; yields a function taking the fault."""
    made = []

    def serve(fault):
        path = Path(tempfile.mkdtemp(prefix="sc")) / "s"
        pem = Path(certificate[0]).read_text()
        made.append(FakeConsole(path, pem, seed_password="x", fault=fault))
        return str(path)

    yield serve
    for c in made:
        c.close()


def test_a_console_that_shows_a_login_prompt_after_the_reboot_passes(update, console):
    status, output, _ = update(env={"SERIAL_SOCKET": console(None), "CONSOLE_WAIT": "20"})

    assert status == 0
    assert f"{CHECK}: PASS" in output


def test_an_unlocked_console_that_shows_its_menu_after_the_reboot_passes(update, console):
    status, output, _ = update(env={"SERIAL_SOCKET": console("unlocked"), "CONSOLE_WAIT": "20"})

    assert status == 0
    assert f"{CHECK}: PASS" in output


def test_a_console_that_says_nothing_after_the_reboot_fails(update, tmp_path):
    path = tempfile.mkdtemp(prefix="sc") + "/s"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    held = []
    threading.Thread(target=lambda: held.append(server.accept()), daemon=True).start()

    status, output, _ = update(env={"SERIAL_SOCKET": path, "CONSOLE_WAIT": "3"})

    server.close()
    assert status != 0
    assert f"{CHECK}: FAIL" in output
