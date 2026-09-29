#!/usr/bin/env python3
"""Writes the registry override for deploy-ordering-check's own two ansible-playbook
invocations to pass via `-e @<o>`: only the entries with `store: controller_file`, the
controller-side file cache.

That job exercises the real ansible_host -> ddns_domain -> main_domain ->
secrets_generated chain against the real secrets_registry.yaml (see
ci-deploy-ordering-inventory.yaml's own header comment for why it can't use a
separate, stubbed-out registry the normal way group_vars overrides work). It
has no real OpenBao/step-ca target, so a registry with any OpenBao-stored
entry makes vault_login.yaml run and fail loudly (no AppRole provisioned, and
even a dummy AppRole would still try to reach a nonexistent `security` host).
Vault reachability is covered for real by the `secrets` role's own
vault_backed/rotate_secret Molecule scenarios; this job only tests ordering.

The chain resolves `main-domain` from the file cache and reads nothing else,
so the file-cache entries are all it needs. Selecting them from the real
registry at CI-run time, not hand-maintaining a stub, means the override
can't drift from it and no entry is rewritten. `main-domain` missing from the
selection is an error: without it the job would test nothing.

Output is JSON, not YAML: Ansible's `-e @file` loader accepts either, and
json.dump needs no dependency beyond the standard library.

Usage (from tools/): python -m ci.fixtures.file_cache_registry <output-path>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from utils.secrets_registry import REGISTRY_PATH, Registry, RegistryError, file_cache_entries, load_registry

REQUIRED = "main-domain"


def file_cache_registry(registry: Registry) -> Registry:
    """The override: `registry`'s file-cache entries, which must include `main-domain`."""
    entries = file_cache_entries(registry)
    if REQUIRED not in entries:
        raise RegistryError(f"`{REQUIRED}` isn't a file-cache entry, so the ordering check would have nothing to resolve ansible_host from")
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("output")
    args = parser.parse_args(argv)
    try:
        override = file_cache_registry(load_registry(REGISTRY_PATH))
    except RegistryError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    Path(args.output).write_text(json.dumps({"secrets_registry": override}))
    print(f"Wrote {len(override)} file-cache entries to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
