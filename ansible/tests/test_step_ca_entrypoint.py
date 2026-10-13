"""Tests for docker/step-ca/scripts/entrypoint.sh, the script that creates the real CA.

Run via `uv run pytest ansible/tests/ -v`. The script runs unmodified under `sh`
with stand-ins for `step` and `step-ca` first on PATH. The stand-ins record every
call and nothing else, so no CA is created and nothing is signed; what is checked
is which commands the script runs, in which order, with which arguments and files.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[2] / "docker/step-ca/scripts/entrypoint.sh"
# The script writes both passwords to fixed paths, not under TMPDIR.
PASSWORD_FILES = (Path("/tmp/step-ca-password"), Path("/tmp/step-ca-provisioner-password"))

STUB = """#!/bin/sh
printf '%s' "$(basename "$0")" >> "$CALL_LOG"
for arg in "$@"; do printf '\\t%s' "$arg" >> "$CALL_LOG"; done
printf '\\n' >> "$CALL_LOG"
{extra}
"""
# `step ca init` is what writes the CA's config; the second guard of a rerun is that file.
STEP_EXTRA = """if [ "$1 $2" = "ca init" ] && [ -z "${STUB_INIT_FAILS:-}" ]; then
    mkdir -p "$STEPPATH/config"
    : > "$STEPPATH/config/ca.json"
fi
if [ "$1 $2" = "ca init" ] && [ -n "${STUB_INIT_FAILS:-}" ]; then
    exit 1
fi"""

ENV = {
    "STEP_CA_NAME": "Homelab CA",
    "STEP_CA_DNS_NAMES": "step-ca,ca.lan.example",
    "STEP_CA_PROVISIONER_NAME": "internal-services",
    "STEP_CA_PASSWORD": "ca-password",
    "STEP_CA_PROVISIONER_PASSWORD": "provisioner-password",
    "STEP_CA_DEFAULT_CERT_DURATION": "720h",
}


@pytest.fixture(autouse=True)
def _clean_password_files():
    for path in PASSWORD_FILES:
        path.unlink(missing_ok=True)
    yield
    for path in PASSWORD_FILES:
        path.unlink(missing_ok=True)


@pytest.fixture
def sandbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("stepca")
    bin_dir = root / "bin"
    bin_dir.mkdir()
    for name, extra in (("step", STEP_EXTRA), ("step-ca", "")):
        stub = bin_dir / name
        stub.write_text(STUB.format(extra=extra))
        stub.chmod(0o755)
    (root / "step").mkdir()
    return root


def run_entrypoint(sandbox: Path, **overrides: str | None) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    """Run the script; returns the process and each stand-in call as [command, *arguments]."""
    env = {"PATH": f"{sandbox / 'bin'}:{os.environ['PATH']}", "STEPPATH": str(sandbox / "step"), "CALL_LOG": str(sandbox / "calls.log"), **ENV}
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    result = subprocess.run(["sh", str(ENTRYPOINT)], env=env, capture_output=True, text=True, check=False)
    log = sandbox / "calls.log"
    calls = [line.split("\t") for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


class TestFirstStart:
    def test_initialises_the_ca_then_sets_the_provisioner_duration_then_starts_it(self, sandbox):
        config = sandbox / "step/config/ca.json"

        result, calls = run_entrypoint(sandbox)

        assert result.returncode == 0, result.stderr
        assert calls == [
            [
                "step",
                "ca",
                "init",
                "--name",
                "Homelab CA",
                "--dns",
                "step-ca,ca.lan.example",
                "--address",
                ":9000",
                "--provisioner",
                "internal-services",
                "--password-file",
                "/tmp/step-ca-password",
                "--provisioner-password-file",
                "/tmp/step-ca-provisioner-password",
                "--deployment-type",
                "standalone",
            ],
            ["step", "ca", "provisioner", "update", "internal-services", "--ca-config", str(config), "--x509-default-dur", "720h"],
            ["step-ca", str(config), "--password-file", "/tmp/step-ca-password"],
        ]

    def test_the_two_passwords_are_independent_private_files_without_a_trailing_newline(self, sandbox):
        run_entrypoint(sandbox)

        ca_password, provisioner_password = PASSWORD_FILES
        assert ca_password.read_text() == "ca-password"
        assert provisioner_password.read_text() == "provisioner-password"
        assert stat.S_IMODE(ca_password.stat().st_mode) == 0o600
        assert stat.S_IMODE(provisioner_password.stat().st_mode) == 0o600

    def test_a_failed_init_never_starts_the_ca(self, sandbox):
        result, calls = run_entrypoint(sandbox, STUB_INIT_FAILS="1")

        assert result.returncode != 0
        assert [call[0] for call in calls] == ["step"]


class TestRestart:
    def test_an_existing_config_skips_the_bootstrap_and_only_starts_the_ca(self, sandbox):
        config = sandbox / "step/config/ca.json"
        config.parent.mkdir(parents=True)
        config.write_text("{}")

        result, calls = run_entrypoint(sandbox)

        assert result.returncode == 0, result.stderr
        assert calls == [["step-ca", str(config), "--password-file", "/tmp/step-ca-password"]]
        assert config.read_text() == "{}"


class TestMissingSettings:
    @pytest.mark.parametrize("name", sorted(ENV), ids=sorted(ENV))
    def test_an_unset_setting_stops_the_script_before_the_ca_starts(self, sandbox, name):
        result, calls = run_entrypoint(sandbox, **{name: None})

        assert result.returncode != 0
        assert "step-ca" not in [call[0] for call in calls]
