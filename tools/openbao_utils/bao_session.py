#!/usr/bin/env python3
"""Log in to OpenBao and hand off to a real interactive shell with a
native `bao` CLI already wired up - usable from either `security` or
`controller`. Replaces docker/openbao/scripts/bao-login.sh,
bao-login-from-controller.sh, and bao-from-controller.sh (three
scripts, two of them docker-exec/docker-run based) with one script
that talks to the native `bao` binary both hosts now have (Stages 2
and 4 of docs/projects/openbao-cli-standardization.md). See
docs/decisions/drafts/openbao-native-cli-not-docker-based-access.md's
Decision for the full reasoning this module implements.

Authenticates via openbao_utils.client.vault_login() (hvac) rather
than shelling out to `bao write auth/approle/login`: secret_id is read
with getpass straight into memory and passed as a function argument,
never a file on disk or a subprocess argument - the temp-file dance
bao-login.sh/bao-login-from-controller.sh both used is gone entirely,
not just hidden better.

Once logged in, this spawns a real interactive child shell (inheriting
the terminal) with BAO_ADDR/BAO_CACERT/BAO_TLS_SERVER_NAME/BAO_TOKEN
exported for that child process only, so any native `bao` subcommand
(kv get, operator raft snapshot save, ...) keeps working completely
unmodified inside it. The token is revoked when that child exits,
normally or via Ctrl-C - a bounded session, not an open-ended
`export` the operator has to remember to undo.

Root-cert source auto-detects which host this is running on: a local
`docker exec step-ca ...` only succeeds on `security` itself (step-ca
is a sibling container there); anywhere else it fails immediately
(command not found, or no such container) and this falls back to
utils.repo.fetch_root_cert()'s SSH-fetch path (ADR 0022's mechanism).
--controller forces that SSH path, for whenever auto-detection guesses
wrong.

Usage:
    cd tools && python3 -m openbao_utils.bao_session <role_id>
    cd tools && python3 -m openbao_utils.bao_session <role_id> --controller
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import hvac
from utils.repo import STEP_CA_CONTAINER, TIMEOUT_SECONDS, fetch_root_cert

from openbao_utils.client import openbao_base_url, openbao_hostname, vault_login

_LOCAL_ROOT_CERT_CMD = ["docker", "exec", STEP_CA_CONTAINER, "cat", "/home/step/certs/root_ca.crt"]

# Matches `bao version`'s own reported shape, confirmed live in this
# project's Stage 1 spike ("OpenBao v2.6.2 (dd9c19c...)") - pulls out
# just the dotted version, the same form /sys/health's own "version"
# field uses (openbao.org's API docs), so the two are comparable
# directly.
_LOCAL_VERSION_RE = re.compile(r"v(\d+\.\d+\.\d+)")


def _local_root_cert() -> str | None:
    """Only succeeds on `security` itself. Anywhere else - `controller`
    included - `docker exec step-ca` either isn't installed or has no
    such container, and this returns None so the caller falls back to
    the SSH path instead."""
    try:
        result = subprocess.run(_LOCAL_ROOT_CERT_CMD, capture_output=True, timeout=TIMEOUT_SECONDS, check=False)
    except OSError, subprocess.TimeoutExpired:
        return None
    return result.stdout.decode() if result.returncode == 0 else None


def get_root_cert(force_controller: bool) -> str:
    if not force_controller:
        cert = _local_root_cert()
        if cert:
            return cert
    return fetch_root_cert()


def local_bao_version() -> str | None:
    try:
        result = subprocess.run(["bao", "version"], capture_output=True, timeout=TIMEOUT_SECONDS, check=False)
    except OSError, subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    match = _LOCAL_VERSION_RE.search(result.stdout.decode())
    return match.group(1) if match else None


def server_version(client: hvac.Client) -> str | None:
    """Best-effort only - a warning, not a hard fail like
    ansible/roles/openbao_cli's own install-time check, since a
    successful login has already proven the server's reachable and
    shouldn't be blocked by this. hvac's default JSONAdapter decodes a
    200 response into the dict openbao.org's /sys/health docs show (a
    plain "version" field, e.g. "2.6.2" - no "v" prefix, no build
    hash); any other status (503 sealed, 501 uninitialized, ...) comes
    back as a raw requests.Response instead of a dict - treated the
    same as any other read failure here rather than assumed away."""
    try:
        health = client.sys.read_health_status(method="GET")
    except Exception:
        return None
    return health.get("version") if isinstance(health, dict) else None


def warn_on_version_mismatch(client: hvac.Client) -> None:
    local = local_bao_version()
    remote = server_version(client)
    if local and remote and local != remote:
        print(
            f"Warning: local bao ({local}) doesn't match the running server ({remote}) - "
            "bump ansible/roles/openbao_cli's openbao_cli_version (security) and this "
            "host's own native bao (controller) to match.",
            file=sys.stderr,
        )


def spawn_session(env: dict[str, str]) -> int:
    shell = env.get("SHELL", "/bin/sh")
    print(f"Logged in - spawning {shell} with BAO_* exported for this session only. Exit the shell to revoke.")
    try:
        return subprocess.call([shell], env=env)
    except KeyboardInterrupt:
        # Ctrl-C reaches this process and the child shell at once (same
        # foreground process group) - confirmed live during this
        # project's Stage 1 de-risking pass (see the draft's Decision).
        # Caught here so main()'s own finally-block cleanup still runs
        # without an uncaught traceback printing after it.
        return 130


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("role_id")
    parser.add_argument(
        "--controller",
        action="store_true",
        help="Force the SSH-fetch root-cert path, skipping local-docker-exec auto-detection.",
    )
    args = parser.parse_args()

    secret_id = getpass.getpass("secret_id: ")

    ca_path: str | None = None
    client: hvac.Client | None = None
    exit_code = 1
    try:
        with tempfile.NamedTemporaryFile("w", suffix="-openbao-root-ca", delete=False) as f:
            f.write(get_root_cert(args.controller))
            ca_path = f.name

        client = hvac.Client(url=openbao_base_url(), verify=ca_path, timeout=TIMEOUT_SECONDS)
        vault_login(client, args.role_id, secret_id)
        warn_on_version_mismatch(client)

        env = os.environ.copy()
        env["BAO_ADDR"] = openbao_base_url()
        env["BAO_CACERT"] = ca_path
        env["BAO_TLS_SERVER_NAME"] = openbao_hostname()
        env["BAO_TOKEN"] = client.token

        exit_code = spawn_session(env)
    finally:
        if client is not None and client.token:
            try:
                client.auth.token.revoke_self()
            except Exception as exc:
                print(f"Warning: failed to revoke token: {exc}", file=sys.stderr)
        if ca_path:
            Path(ca_path).unlink(missing_ok=True)

    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nAborted - nothing was logged in.", file=sys.stderr)
        raise SystemExit(130) from None
