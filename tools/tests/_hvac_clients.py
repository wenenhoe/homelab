"""A real hvac.Client whose network calls are replaced for a test.

The client is the library's own, so the attributes the code under test
reads and sets (`token`, `sys`, `auth`, `secrets`) are the real ones.
Every request funnels through the adapter, whose methods are autospec'd
stand-ins, so nothing can leave the process; the five calls the code
makes are stubbed on top with the real signatures. A test sets
`.return_value` or `.side_effect` on the one it expects to be called.

`token` starts as None: hvac would otherwise read VAULT_TOKEN or a token
file, and a developer's real token must never reach a test.
"""

from __future__ import annotations

from unittest.mock import create_autospec

import hvac

_ADAPTER_METHODS = ("request", "get", "post", "put", "delete", "list")


def stubbed_hvac_client() -> hvac.Client:
    client = hvac.Client(url="https://openbao.example.com:8200")
    client.token = None
    for name in _ADAPTER_METHODS:
        setattr(client.adapter, name, create_autospec(getattr(client.adapter, name)))
    for owner, name in (
        (client.secrets.kv.v2, "read_secret_version"),
        (client.secrets.kv.v2, "create_or_update_secret"),
        (client.auth.approle, "login"),
        (client.auth.token, "revoke_self"),
        (client.sys, "read_health_status"),
    ):
        setattr(owner, name, create_autospec(getattr(owner, name)))
    return client
