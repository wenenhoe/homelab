"""OpenBao/Vault-specific client primitives: KV v2 read/write and
AppRole login. Shared by every internal Python client that needs
them: cloud_credentials/cache.py (its own session-caching layer sits
on top of this) and bootstrap_secrets.py.

None of this is cloud-credential business - it accreted inside
cloud_credentials/cache.py originally only because leaf/rotation
credentials were its first consumer. The generic repo-navigation and
SSH/root-cert-fetching helpers this module used to also include live
in tools/utils/repo.py instead - they were never actually
OpenBao-specific either, just OpenBao's first (and so far, only)
consumer. See
docs/decisions/0031-tools-secrets-package-split.md.

r2_read_watcher.py deliberately does NOT import this: it's
hand-installed via scp as a single file onto security's system
Python, never part of this uv-managed tools/ tree - sharing code
across that deployment boundary would mean shipping a second file
alongside a script whose whole point is staying one file. It keeps
its own independent copy of the same login/read logic instead.

Uses hvac for the OpenBao client - see
docs/decisions/0030-openbao-hvac-paramiko-clients.md.
"""

from __future__ import annotations

import hvac
from utils.repo import main_domain

VAULT_KV_MOUNT = "secret"


def openbao_base_url() -> str:
    # security's caddy_domain = "sec.{{ lab_domain }}", lab_domain =
    # "lan.{{ main_domain }}" (host_vars/security.yaml, group_vars/all/
    # main.yaml) - update this if either naming convention ever changes.
    return f"https://openbao.sec.lan.{main_domain()}:8200"


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
