"""Read-or-create of one OpenBao KV v2 secret, shared by Ansible modules.

A module imports this as ansible.module_utils.openbao_kv, which
ansible.cfg's module_utils setting makes resolvable.

tools/openbao_utils/client.py makes the same hvac calls and is a separate
implementation on purpose: a module cannot import it, and neither tree
depends on the other. A change to KV v2 behaviour needs applying to both.
See docs/decisions/0067-where-the-code-that-generates-and-stores-a-vault-backed-secret-lives/revision-000.md.
"""

from __future__ import annotations

import math
import secrets
import uuid
from typing import NamedTuple

import hvac
import requests

VAULT_KV_MOUNT = "secret"


class Resolved(NamedTuple):
    value: str
    generated: bool


class SecretNotStoredError(Exception):
    """The create was rejected and the path still holds nothing."""


# What a failed OpenBao exchange raises: an API error, an unreachable or
# misbehaving server, or a rejected write nobody else filled in. A caller
# reports these as a failed task and lets any other exception crash.
EXPECTED_ERRORS = (hvac.exceptions.VaultError, requests.exceptions.RequestException, SecretNotStoredError, ValueError)


def new_client(base_url: str, token: str, ca_path: str | None) -> hvac.Client:
    return hvac.Client(url=base_url, token=token, verify=ca_path or True)


def generate_value(source: str, length: int | None) -> str:
    if source == "hex":
        if length is None or length < 1:
            msg = f"a hex secret needs a positive length, got {length!r}"
            raise ValueError(msg)
        # token_hex(n) returns 2n characters, so an odd length takes one more
        # byte than it needs and is cut to the exact length.
        return secrets.token_hex(math.ceil(length / 2))[:length]
    if source == "uuid4":
        return str(uuid.uuid4())
    msg = f"unsupported source {source!r}"
    raise ValueError(msg)


def read_value(client: hvac.Client, path: str, mount_point: str = VAULT_KV_MOUNT) -> str | None:
    try:
        resp = client.secrets.kv.v2.read_secret_version(
            path=path,
            mount_point=mount_point,
            # A deleted version reads the same as one that never existed.
            # hvac's default only matches that until v3.0.0 flips it, which
            # would return metadata with no "value" key instead.
            raise_on_deleted_version=True,
        )
    except hvac.exceptions.InvalidPath:
        return None
    return resp["data"]["data"]["value"]


def ensure_value(client: hvac.Client, path: str, mount_point: str, source: str, length: int | None) -> Resolved:
    existing = read_value(client, path, mount_point)
    if existing is not None:
        return Resolved(existing, False)

    value = generate_value(source, length)
    try:
        # cas=0 writes only if the path does not exist yet, so of two runs
        # creating the same secret at once exactly one write lands.
        client.secrets.kv.v2.create_or_update_secret(path=path, secret={"value": value}, cas=0, mount_point=mount_point)
    except hvac.exceptions.InvalidRequest as err:
        # Lost the race: the winner's value is the authoritative one, not the
        # value this run generated and never stored.
        winner = read_value(client, path, mount_point)
        if winner is None:
            msg = f"the write to {path} was rejected and the path is still empty: {err}"
            raise SecretNotStoredError(msg) from err
        return Resolved(winner, False)
    return Resolved(value, True)
