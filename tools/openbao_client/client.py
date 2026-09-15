"""Generic OpenBao/Vault client primitives, shared by every internal
Python client that needs them: cloud_credentials/cache.py (its own
session-caching layer sits on top of this) and bootstrap_secrets.py.

None of this is cloud-credential business - it accreted inside
cloud_credentials/cache.py originally only because leaf/rotation
credentials were its first consumer. See
docs/decisions/drafts/tools-directory-and-secrets-package-split.md.

r2_read_watcher.py deliberately does NOT import this: it's
hand-installed via scp as a single file onto security's system
Python, never part of this uv-managed tools/ tree - sharing code
across that deployment boundary would mean shipping a second file
alongside a script whose whole point is staying one file. It keeps
its own independent copy of the same login/read logic instead.

Uses hvac for the OpenBao client and paramiko for the SSH root-cert
fetch - see docs/decisions/0030-openbao-hvac-paramiko-clients.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import hvac
import paramiko
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SECRETS_DIR = PROJECT_ROOT / "ansible/files/secrets"
INVENTORY_PATH = PROJECT_ROOT / "ansible/inventory/inventory.yaml"

VAULT_KV_MOUNT = "secret"
VAULT_STEP_CA_CONTAINER = "step-ca"
# Bounds both the SSH root-cert fetch and every Vault HTTP call. The SSH
# fetch previously had no timeout at all in either of this module's two
# original callers (the bug docs/decisions/0030-openbao-hvac-paramiko-clients.md
# fixed) - one number to reason about, not two.
TIMEOUT_SECONDS = 10


def read_bootstrap_file(name: str) -> str | None:
    """main-domain and openbao-controller-role-id/-secret-id live
    permanently in the file cache instead, read directly from
    SECRETS_DIR, never through Vault - the credentials Vault access
    itself depends on, so they can't live in the thing they unlock."""
    path = SECRETS_DIR / name
    return path.read_text().strip() if path.exists() else None


def main_domain() -> str:
    domain = read_bootstrap_file("main-domain")
    if not domain:
        print(
            "main-domain isn't cached yet - it's needed to reach OpenBao at all "
            "(secrets_registry.yaml's header comment explains why it never moves "
            "into Vault). Set it first:\n"
            f"  printf '%s' '<your-domain>' > {SECRETS_DIR / 'main-domain'}\n"
            f"  chmod 600 {SECRETS_DIR / 'main-domain'}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return domain


def openbao_base_url() -> str:
    # security's caddy_domain = "sec.{{ lab_domain }}", lab_domain =
    # "lan.{{ main_domain }}" (host_vars/security.yaml, group_vars/all/
    # main.yaml) - update this if either naming convention ever changes.
    return f"https://openbao.sec.lan.{main_domain()}:8200"


def security_ssh_target() -> tuple[str, str, str]:
    """(user, host, key_path) for SSH to `security`, read from
    inventory.yaml rather than hardcoded twice."""
    with INVENTORY_PATH.open() as f:
        inv = yaml.safe_load(f)
    user = inv["all"]["children"]["managed_hosts"]["hosts"]["security"]["ansible_user"]
    key_path = Path(inv["all"]["vars"]["ansible_ssh_private_key_file"]).expanduser()
    host = f"security.internal.{main_domain()}"  # ddns_domain, see inventory.yaml
    return user, host, str(key_path)


def fetch_root_cert() -> str:
    user, host, key_path = security_ssh_target()
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    # Trust-on-first-use, same as the previous StrictHostKeyChecking=
    # accept-new: system known_hosts is checked first, and paramiko's
    # transport still raises BadHostKeyException on a mismatch against
    # an already-known host regardless of this policy - fail-closed on
    # a changed key, not blanket trust. Confirmed live against a real
    # host - see docs/decisions/0030-openbao-hvac-paramiko-clients.md.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=user, key_filename=key_path, timeout=TIMEOUT_SECONDS)
        _stdin, stdout, stderr = client.exec_command(
            f"docker exec {VAULT_STEP_CA_CONTAINER} cat /home/step/certs/root_ca.crt",
            timeout=TIMEOUT_SECONDS,
        )
        cert = stdout.read().decode()
        err = stderr.read().decode()
        exit_status = stdout.channel.recv_exit_status()
    finally:
        client.close()
    if exit_status != 0:
        print(f"Failed to fetch step-ca's root cert from {host}: {err}", file=sys.stderr)
        raise SystemExit(1)
    return cert


def vault_login(client: hvac.Client, role_id: str, secret_id: str) -> None:
    client.auth.approle.login(role_id=role_id, secret_id=secret_id)  # sets client.token


def vault_read(client: hvac.Client, path: str, mount_point: str = VAULT_KV_MOUNT) -> str | None:
    try:
        resp = client.secrets.kv.v2.read_secret_version(
            path=path,
            mount_point=mount_point,
            # A deleted version should read the same as one that never
            # existed. hvac's default silently matches this already,
            # but only with a DeprecationWarning ahead of hvac v3.0.0
            # flipping it to False, which would instead return
            # metadata with no "value" key.
            raise_on_deleted_version=True,
        )
    except hvac.exceptions.InvalidPath:
        return None
    return resp["data"]["data"]["value"]


def vault_write(client: hvac.Client, path: str, value: str, mount_point: str = VAULT_KV_MOUNT) -> None:
    client.secrets.kv.v2.create_or_update_secret(path=path, secret={"value": value}, mount_point=mount_point)
