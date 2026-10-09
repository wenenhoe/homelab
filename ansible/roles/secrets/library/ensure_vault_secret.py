#!/usr/bin/python

from __future__ import annotations

DOCUMENTATION = r"""
module: ensure_vault_secret
short_description: Return a Vault-backed secret's value, creating it first when none exists
description:
  - Reads the OpenBao KV v2 secret at C(scope)/C(name). When the path holds nothing, generates a value, stores it with C(cas=0) and returns it.
  - When a concurrent run creates the secret first, returns that run's value, not the one this run generated.
  - The returned C(value) is the secret in plain text. The module cannot hide it, so every task that calls this module must set C(no_log=true).
author:
  - Hoe Wen En (@wenenhoe)
options:
  name:
    description: The secret's catalog key, the last segment of its KV path.
    type: str
    required: true
  source:
    description: How a missing value is generated.
    type: str
    required: true
    choices: [hex, uuid4]
  length:
    description: Characters in a generated C(hex) value. Required when I(source=hex).
    type: int
  scope:
    description: The KV path above the secret, such as C(hosts/security).
    type: str
    required: true
  kv_mount:
    description: The KV v2 mount point.
    type: str
    default: secret
  vault_base_url:
    description: OpenBao's base URL.
    type: str
    required: true
  vault_token:
    description: A token allowed to read and create the secret.
    type: str
    required: true
  vault_ca_path:
    description: A CA bundle to verify OpenBao's certificate against. The system store is used when unset.
    type: path
attributes:
  check_mode:
    support: none
    details: Generation only happens when a read finds nothing, so there is nothing meaningful to preview.
"""

EXAMPLES = r"""
- name: Resolve a generated secret
  ensure_vault_secret:
    name: lldap-jwt-secret
    source: hex
    length: 40
    scope: hosts/security
    vault_base_url: "{{ secrets_vault_base_url }}"
    vault_token: "{{ secrets_vault_token }}"
    vault_ca_path: "{{ secrets_vault_ca_path }}"
  register: resolved
  no_log: true
"""

RETURN = r"""
value:
  description: The secret's value, in plain text.
  type: str
  returned: success
generated:
  description: Whether this run created the secret. C(false) when it already existed or another run created it first.
  type: bool
  returned: success
"""

# Ansible's module convention is documentation first, imports after it.
from ansible.module_utils.basic import AnsibleModule  # noqa: E402

from ansible.module_utils.openbao_kv import EXPECTED_ERRORS, VAULT_KV_MOUNT, ensure_value, new_client  # noqa: E402


def main() -> None:
    module = AnsibleModule(
        argument_spec={
            "name": {"type": "str", "required": True},
            "source": {"type": "str", "required": True, "choices": ["hex", "uuid4"]},
            "length": {"type": "int"},
            "scope": {"type": "str", "required": True},
            "kv_mount": {"type": "str", "default": VAULT_KV_MOUNT},
            "vault_base_url": {"type": "str", "required": True},
            "vault_token": {"type": "str", "required": True, "no_log": True},
            "vault_ca_path": {"type": "path"},
        },
        required_if=[("source", "hex", ("length",))],
        supports_check_mode=False,
    )
    params = module.params
    path = f"{params['scope']}/{params['name']}"
    try:
        client = new_client(params["vault_base_url"], params["vault_token"], params["vault_ca_path"])
        resolved = ensure_value(client, path, params["kv_mount"], params["source"], params["length"])
    except EXPECTED_ERRORS as err:
        module.fail_json(msg=f"{path}: {err}")
    module.exit_json(changed=resolved.generated, value=resolved.value, generated=resolved.generated)


if __name__ == "__main__":
    main()
