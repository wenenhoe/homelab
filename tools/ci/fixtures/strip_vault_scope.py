#!/usr/bin/env python3
"""Writes a copy of secrets_registry.yaml with vault_scope stripped from
every entry, for deploy-ordering-check's own two ansible-playbook
invocations to pass via `-e @<output>`.

That job exercises the real ansible_host -> ddns_domain -> main_domain ->
secrets_generated chain against the real secrets_registry.yaml (see
ci-deploy-ordering-inventory.yaml's own header comment for why it can't use
a separate, stubbed-out registry the normal way group_vars overrides work).
But it has no real OpenBao/step-ca target, and most registry entries have a
vault_scope, so passing the real registry as-is makes vault_login.yaml
actually run and fail loudly (no AppRole provisioned, and even a dummy
AppRole would still try to reach a nonexistent `security` host). Vault
reachability is already covered for real by the `secrets` role's own
vault_backed/rotate_secret Molecule scenarios; this job only ever tested
ordering.

Stripping vault_scope, not swapping in a hand-maintained stub registry, so
this can't drift from the real one: every entry still exists with its real
format/length/allow_blank/sensitive/description, resolved from the file
cache, which is exactly the behavior this job needs.

Output is JSON, not YAML: Ansible's `-e @file` loader accepts either, and
json.dump needs no dependency beyond the standard library.

Usage (from tools/): python -m ci.fixtures.strip_vault_scope <output-path>
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from ci.fixtures.secrets_registry import REPO_ROOT, RegistryError, load_registry


def strip_vault_scope(registry: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    """A copy of `registry` with `vault_scope` removed from every entry."""
    stripped = copy.deepcopy(registry)
    for spec in stripped.values():
        spec.pop("vault_scope", None)
    return stripped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("output")
    args = parser.parse_args(argv)
    try:
        registry = strip_vault_scope(load_registry(REPO_ROOT))
    except RegistryError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    Path(args.output).write_text(json.dumps({"secrets_registry": registry}))
    print(f"Wrote {len(registry)} entries (vault_scope stripped) to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
