#!/usr/bin/env python3
"""Writes a copy of secrets_registry.yaml with vault_scope stripped
from every entry, for deploy-ordering-check's own two ansible-playbook
invocations to pass via -e @<output>.

That job exercises the real ansible_host -> ddns_domain -> main_domain
-> secrets_generated chain against the real secrets_registry.yaml (see
ci-deploy-ordering-inventory.yaml's own header comment for why it can't
use a separate, stubbed-out registry the normal way group_vars
overrides work). But it has no real OpenBao/step-ca target, and
Track A stage 4 gave most registry entries a vault_scope — so passing
the real registry as-is now makes vault_login.yaml actually run and
fail loudly (no AppRole provisioned, and even a dummy AppRole would
still try to reach a nonexistent `security` host). Vault reachability
is already covered for real by the `secrets` role's own vault_backed/
rotate_secret Molecule scenarios; this job was only ever testing
ordering, never Vault connectivity.

Stripping vault_scope, not swapping in a hand-maintained stub registry,
so this script can't drift from the real one — every entry still
exists with its real format/length/allow_blank/sensitive/description,
just resolved from the file cache the way every entry worked before
Track A stage 4, which is exactly the behavior this job actually needs.

Output is JSON, not YAML: Ansible's `-e @file` extra-vars loader
accepts either, and json.dump needs no extra dependency beyond the
stdlib, unlike re-emitting YAML.

Usage:
    python3 .github/scripts/strip-vault-scope-for-ci.py <output-path>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "ansible/inventory/group_vars/all/secrets_registry.yaml"


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <output-path>", file=sys.stderr)
        return 1
    output_path = Path(sys.argv[1])

    with REGISTRY_PATH.open() as f:
        data = yaml.safe_load(f)

    registry = data["secrets_registry"]
    for entry in registry.values():
        entry.pop("vault_scope", None)

    output_path.write_text(json.dumps({"secrets_registry": registry}))
    print(f"Wrote {len(registry)} entries (vault_scope stripped) to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
