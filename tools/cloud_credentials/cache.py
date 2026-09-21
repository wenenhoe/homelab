"""Vault-backed cache for cloud_credentials' leaf and rotation credentials.

Every leaf_keys/rotation_keys module, check_freshness.py, and the
top-level create_*.py scripts read/write through the four functions
scoped() returns - never a raw HTTP call of their own. Storage target
is OpenBao KV v2, at secret/data/cloud_credentials/<category>/<name>
(controller's Era A AppRole, ADR 0020, already grants read/write on
both leaf/* and rotation/*). read_vault_path() is the one exception:
a direct read for the rare caller needing a Vault path outside that
taxonomy (see its own docstring).

Session/TLS-trust mechanics (fetch step-ca's root cert, log in via
AppRole, read/write KV v2) come from tools.utils.repo/tools.openbao_utils.client -
shared with openbao_utils/bootstrap.py, no longer duplicated between them.
This module's own job is just the leaf/rotation Vault-path taxonomy
and scoped()'s session-caching convenience on top of those primitives.
See docs/decisions/0031-where-repo-tooling-lives/revision-000.md.

Two secrets live permanently in the file cache instead, read directly
from SECRETS_DIR below, never through Vault: main-domain and
openbao-controller-role-id/-secret-id - the credentials Vault access
itself depends on, so they can't live in the thing they unlock (see
secrets_registry.yaml's header comment for the equivalent exception on
the Ansible side).
"""

from __future__ import annotations

import atexit
import sys
import tempfile
from pathlib import Path

import hvac
from openbao_utils.client import openbao_base_url, vault_read, vault_write
from openbao_utils.client import vault_login as _bare_vault_login
from utils.repo import TIMEOUT_SECONDS, fetch_root_cert, read_bootstrap_file

_VALID_CATEGORIES = ("leaf", "rotation")


def _vault_login(client: hvac.Client) -> None:
    role_id = read_bootstrap_file("openbao-controller-role-id")
    secret_id = read_bootstrap_file("openbao-controller-secret-id")
    if not role_id or not secret_id:
        print(
            "openbao-controller-role-id/-secret-id aren't set yet - run "
            "docs/openbao-auth.md's runbook (Track A stage 3) before using "
            "any part of cloud_credentials.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    _bare_vault_login(client, role_id, secret_id)


_session: dict[str, hvac.Client | str] | None = None


def _get_session() -> dict[str, hvac.Client | str]:
    """Logs in once per process, on first use - every cached()/
    read_cache()/write_cache()/require_cache_file() call for the rest of
    this run reuses the same hvac.Client/ca_path. Cleaned up at process
    exit (atexit), not after each call: unlike openbao_utils/bootstrap.py's
    single try/finally around one run, cloud_credentials scripts make
    many sequential Vault calls across a whole invocation (e.g. every
    leaf across all three providers in one create_leaf_keys.py run)."""
    global _session
    if _session is None:
        fd, ca_path = tempfile.mkstemp(suffix="-openbao-root-ca")
        with open(fd, "w") as f:
            f.write(fetch_root_cert())
        atexit.register(lambda: Path(ca_path).unlink(missing_ok=True))
        client = hvac.Client(url=openbao_base_url(), verify=ca_path, timeout=TIMEOUT_SECONDS)
        _vault_login(client)
        _session = {"client": client, "ca_path": ca_path}
    return _session


def _vault_path(category: str, name: str) -> str:
    if category not in _VALID_CATEGORIES:
        raise ValueError(f"unknown cloud_credentials Vault category: {category!r}")
    return f"cloud_credentials/{category}/{name}"


def _vault_read_at(full_path: str) -> str | None:
    return vault_read(_get_session()["client"], full_path)


def _vault_write_at(full_path: str, value: str) -> None:
    vault_write(_get_session()["client"], full_path, value)


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
