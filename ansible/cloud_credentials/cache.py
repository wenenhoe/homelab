"""Vault-backed cache for cloud_credentials' leaf and rotation credentials.

Every leaf_keys/rotation_keys module, check_freshness.py, and the
top-level create_*.py scripts read/write through the four functions
scoped() returns - never a raw HTTP call of their own. Storage target
is OpenBao KV v2, at secret/data/cloud_credentials/<category>/<name>
(controller's Era A AppRole, ADR 0020, already grants read/write on
both leaf/* and rotation/*). read_vault_path() is the one exception:
a direct read for the rare caller needing a Vault path outside that
taxonomy (see its own docstring).

Vault session/TLS-trust mechanics mirror ansible/bootstrap_secrets.py's
own (ADR 0022): this package runs standalone, outside any Ansible play,
so it fetches step-ca's root cert and logs in via AppRole itself rather
than delegating to the secrets role. Duplicated rather than shared with
bootstrap_secrets.py - the two are deliberately independent, see
ansible/tests/test_bootstrap_secrets.py's own comment on why.

Two secrets live permanently in the file cache instead, read directly
from SECRETS_DIR below, never through Vault: main-domain and
openbao-controller-role-id/-secret-id - the credentials Vault access
itself depends on, so they can't live in the thing they unlock (see
secrets_registry.yaml's header comment for the equivalent exception on
the Ansible side).
"""

from __future__ import annotations

import atexit
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SECRETS_DIR = PROJECT_ROOT / "ansible/files/secrets"
INVENTORY_PATH = PROJECT_ROOT / "ansible/inventory/inventory.yaml"

VAULT_KV_MOUNT = "secret"
VAULT_STEP_CA_CONTAINER = "step-ca"
_VALID_CATEGORIES = ("leaf", "rotation")


def _read_bootstrap_file(name: str) -> str | None:
    path = SECRETS_DIR / name
    return path.read_text().strip() if path.exists() else None


def _main_domain() -> str:
    main_domain = _read_bootstrap_file("main-domain")
    if not main_domain:
        print(
            "main-domain isn't cached yet - it's needed to reach OpenBao at all "
            "(secrets_registry.yaml's header comment explains why it never moves "
            "into Vault). Set it first:\n"
            f"  printf '%s' '<your-domain>' > {SECRETS_DIR / 'main-domain'}\n"
            f"  chmod 600 {SECRETS_DIR / 'main-domain'}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return main_domain


def _openbao_base_url() -> str:
    # security's caddy_domain = "sec.{{ lab_domain }}", lab_domain =
    # "lan.{{ main_domain }}" (host_vars/security.yaml, group_vars/all/
    # main.yaml). Duplicated from bootstrap_secrets.py's identical
    # helper rather than shared - update both if either naming
    # convention ever changes.
    return f"https://openbao.sec.lan.{_main_domain()}:8200"


def _security_ssh_target() -> tuple[str, str, str]:
    """(user, host, key_path) for SSH to `security`, read from
    inventory.yaml rather than hardcoded twice."""
    with INVENTORY_PATH.open() as f:
        inv = yaml.safe_load(f)
    user = inv["all"]["children"]["managed_hosts"]["hosts"]["security"]["ansible_user"]
    key_path = Path(inv["all"]["vars"]["ansible_ssh_private_key_file"]).expanduser()
    host = f"security.internal.{_main_domain()}"  # ddns_domain, see inventory.yaml
    return user, host, str(key_path)


def _fetch_root_cert() -> str:
    user, host, key_path = _security_ssh_target()
    result = subprocess.run(
        [
            "ssh",
            "-i",
            key_path,
            "-o",
            "StrictHostKeyChecking=accept-new",
            f"{user}@{host}",
            "docker",
            "exec",
            VAULT_STEP_CA_CONTAINER,
            "cat",
            "/home/step/certs/root_ca.crt",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"Failed to fetch step-ca's root cert from {host}: {result.stderr}", file=sys.stderr)
        raise SystemExit(1)
    return result.stdout


def _vault_login(ca_path: str) -> str:
    role_id = _read_bootstrap_file("openbao-controller-role-id")
    secret_id = _read_bootstrap_file("openbao-controller-secret-id")
    if not role_id or not secret_id:
        print(
            "openbao-controller-role-id/-secret-id aren't set yet - run "
            "docs/openbao-auth.md's runbook (Track A stage 3) before using "
            "any part of cloud_credentials.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    resp = requests.post(
        f"{_openbao_base_url()}/v1/auth/approle/login",
        json={"role_id": role_id, "secret_id": secret_id},
        verify=ca_path,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["auth"]["client_token"]


_session: dict[str, str] | None = None


def _get_session() -> dict[str, str]:
    """Logs in once per process, on first use - every cached()/
    read_cache()/write_cache()/require_cache_file() call for the rest of
    this run reuses the same token/ca_path. Cleaned up at process exit
    (atexit), not after each call: unlike bootstrap_secrets.py's single
    try/finally around one run, cloud_credentials scripts make many
    sequential Vault calls across a whole invocation (e.g. every leaf
    across all three providers in one create_leaf_keys.py run)."""
    global _session
    if _session is None:
        fd, ca_path = tempfile.mkstemp(suffix="-openbao-root-ca")
        with open(fd, "w") as f:
            f.write(_fetch_root_cert())
        atexit.register(lambda: Path(ca_path).unlink(missing_ok=True))
        token = _vault_login(ca_path)
        _session = {"token": token, "ca_path": ca_path}
    return _session


def _vault_path(category: str, name: str) -> str:
    if category not in _VALID_CATEGORIES:
        raise ValueError(f"unknown cloud_credentials Vault category: {category!r}")
    return f"cloud_credentials/{category}/{name}"


def _vault_read_at(full_path: str) -> str | None:
    session = _get_session()
    resp = requests.get(
        f"{_openbao_base_url()}/v1/{VAULT_KV_MOUNT}/data/{full_path}",
        headers={"X-Vault-Token": session["token"]},
        verify=session["ca_path"],
        timeout=10,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()["data"]["data"]["value"]


def _vault_write_at(full_path: str, value: str) -> None:
    session = _get_session()
    resp = requests.post(
        f"{_openbao_base_url()}/v1/{VAULT_KV_MOUNT}/data/{full_path}",
        headers={"X-Vault-Token": session["token"]},
        json={"data": {"value": value}},
        verify=session["ca_path"],
        timeout=10,
    )
    resp.raise_for_status()


def read_vault_path(full_path: str) -> str | None:
    """Read an arbitrary Vault KV v2 path directly, for the rare caller
    outside the cloud_credentials/{leaf,rotation} taxonomy scoped()
    covers - e.g. check_freshness.py's telegram-* reads, which live
    under the secrets role's own hosts/all/telegram/* convention
    (ADR 0021), a different top-level path this package doesn't own.
    Controller's Era A AppRole already grants read/write on all of
    secret/data/hosts/* (ADR 0020), so no policy change is needed to
    use this from cloud_credentials.
    """
    return _vault_read_at(full_path)


def write_vault_path(full_path: str, value: str) -> None:
    """Write an arbitrary Vault KV v2 path directly - read_vault_path's
    write counterpart, same rare-caller-outside-the-taxonomy case (e.g.
    restoring hosts/* material after a re-init). Controller's Era A
    AppRole already grants create/update on all of secret/data/hosts/*
    (ADR 0020), so no policy change is needed to use this from
    cloud_credentials."""
    _vault_write_at(full_path, value)


def _vault_read(category: str, name: str) -> str | None:
    return _vault_read_at(_vault_path(category, name))


def _vault_write(category: str, name: str, value: str) -> None:
    _vault_write_at(_vault_path(category, name), value)


def scoped(category: str):
    """Returns (cached, read_cache, write_cache, require_cache_file) bound
    to one Vault category - "leaf" or "rotation", ADR 0020's two
    top-level cloud_credentials paths. Each leaf_keys/rotation_keys
    module calls this once, at import time, with its own category: which
    path a key lives under is a property of which module writes it, not
    inferred from the key's name.
    """
    if category not in _VALID_CATEGORIES:
        raise ValueError(f"unknown cloud_credentials Vault category: {category!r}")

    def cached(name: str) -> bool:
        return _vault_read(category, name) is not None

    def read_cache(name: str) -> str | None:
        return _vault_read(category, name)

    def write_cache(name: str, value: str) -> None:
        _vault_write(category, name, value)

    def require_cache_file(name: str, how_to_get_it: str) -> str:
        value = _vault_read(category, name)
        if value is None:
            print(f"Missing required secret: {_vault_path(category, name)}", file=sys.stderr)
            print(f"  {how_to_get_it}", file=sys.stderr)
            sys.exit(1)
        return value

    return cached, read_cache, write_cache, require_cache_file
