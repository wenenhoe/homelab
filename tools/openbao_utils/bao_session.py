#!/usr/bin/env python3
"""Log in to OpenBao and hand off to a real interactive shell with the
native `bao` CLI already wired up, on `controller`. Replaces
docker/openbao/scripts/bao-login.sh, bao-login-from-controller.sh, and
bao-from-controller.sh (three scripts, two of them
docker-exec/docker-run based) with one script that talks to the
native `bao` binary `controller` has (Stage 4 of
docs/projects/openbao-cli-standardization.md). See
docs/decisions/drafts/openbao-native-cli-not-docker-based-access.md's
Decision for the full reasoning this module implements, and
docs/decisions/0033-bao-session-local-only-drops-broken-security-path.md
for why this only ever runs on `controller` - a `security`-local mode
was drafted and never actually worked (the repo isn't checked out
there).

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
unmodified inside it. The token is revoked when that child exits -
normally, via Ctrl-C, or via SIGHUP on an unclean disconnect (see ADR
0033 above) - a bounded session, not an open-ended `export` the
operator has to remember to undo.

step-ca's root cert is always fetched fresh over SSH
(utils.repo.fetch_root_cert(), ADR 0022's mechanism) - `controller`
has no local step-ca container to borrow it from directly.

Usage:
    cd tools && python3 -m openbao_utils.bao_session <role_id>
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import hvac
from utils.repo import TIMEOUT_SECONDS, fetch_root_cert

from openbao_utils.client import openbao_base_url, openbao_hostname, vault_login

# Matches `bao version`'s own reported shape, confirmed live in this
# project's Stage 1 spike ("OpenBao v2.6.2 (dd9c19c...)") - pulls out
# just the dotted version, the same form /sys/health's own "version"
# field uses (openbao.org's API docs), so the two are comparable
# directly.
_LOCAL_VERSION_RE = re.compile(r"v(\d+\.\d+\.\d+)")


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


def _revoke(client: hvac.Client | None) -> None:
    """Idempotent - both the SIGHUP handler and main()'s own finally
    block can reach this for the same session (ADR 0033); clearing
    client.token after a first attempt makes a second call a no-op
    instead of a duplicate revoke warning."""
    if client is not None and client.token:
        try:
            client.auth.token.revoke_self()
        except Exception as exc:
            print(f"Warning: failed to revoke token: {exc}", file=sys.stderr)
        client.token = None


def _cleanup(client: hvac.Client | None, ca_path: str | None) -> None:
    _revoke(client)
    if ca_path:
        Path(ca_path).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("role_id")
    args = parser.parse_args()

    secret_id = getpass.getpass("secret_id: ")

    ca_path: str | None = None
    client: hvac.Client | None = None
    exit_code = 1
    try:
        with tempfile.NamedTemporaryFile("w", suffix="-openbao-root-ca", delete=False) as f:
            f.write(fetch_root_cert())
            ca_path = f.name

        client = hvac.Client(url=openbao_base_url(), verify=ca_path, timeout=TIMEOUT_SECONDS)
        vault_login(client, args.role_id, secret_id)
        warn_on_version_mismatch(client)

        def _on_sighup(signum, frame):
            # sshd sends SIGHUP to this whole process group on an
            # unclean disconnect; Python's default disposition for it
            # is immediate termination, which bypasses the finally
            # block below entirely - confirmed live, see ADR 0033.
            _cleanup(client, ca_path)
            raise SystemExit(1)

        signal.signal(signal.SIGHUP, _on_sighup)

        env = os.environ.copy()
        env["BAO_ADDR"] = openbao_base_url()
        env["BAO_CACERT"] = ca_path
        env["BAO_TLS_SERVER_NAME"] = openbao_hostname()
        env["BAO_TOKEN"] = client.token

        exit_code = spawn_session(env)
    finally:
        _cleanup(client, ca_path)

    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nAborted - nothing was logged in.", file=sys.stderr)
        raise SystemExit(130) from None
