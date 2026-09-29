#!/usr/bin/env python3
"""Writes a throwaway dummy value to ansible/files/secrets/<key> for every
manual secret_catalog entry kept in the file cache, for
deploy-ordering-check's own two ansible-playbook invocations. Mirrors what
openbao_utils/bootstrap.py would produce on a real first-ever deploy, for the
entries the job's catalog override (ci.fixtures.file_cache_catalog) holds.

Driven off the real secret_catalog.yaml at CI-run time rather than a
hand-maintained list of printf lines in the workflow file: the previous
approach needed a new line added there every time a new manual secret was
registered, with nothing enforcing that it actually happened. This can't
drift, since it reads the exact catalog ensure_secret.yaml itself reads.

`allow_blank: true` entries get an empty string: present-but-empty is
valid, not an error, for these (it matches a first-ever deploy before
Beszel, Kuma or OpenBao's AppRole exist). Every other manual entry gets a
generic, traceable dummy value (`ci-dummy-<key>`). deploy-ordering-check
never validates any secret's actual content, since `--tags` filters out
every provisioning play that would use these values, so nothing here needs
to look like a real domain, API key or numeric ID.

A key that isn't a plain file name is refused: the catalog is trusted, but
a key becomes a path here, and a `/` or `..` in one would write outside the
secrets directory.

Usage (from tools/): python -m ci.fixtures.preseed_manual_secrets
"""

from __future__ import annotations

import sys
from pathlib import Path

from utils.secret_catalog import CATALOG_RELATIVE, REPO_ROOT, CatalogError, file_cache_entries, load_catalog

SECRETS_RELATIVE = "ansible/files/secrets"


def manual_values(catalog: dict[str, dict[str, object]]) -> dict[str, str]:
    """Secret name -> dummy value, for every manual file-cache entry."""
    values = {}
    for key, spec in file_cache_entries(catalog).items():
        if spec.get("source") != "manual":
            continue
        if not key or Path(key).name != key or key in {".", ".."}:
            raise CatalogError(f"secret name {key!r} can't be used as a file name")
        values[key] = "" if spec.get("allow_blank") else f"ci-dummy-{key}"
    return values


def preseed(root: Path) -> tuple[int, Path]:
    """Write every manual secret under `root`; return how many and where."""
    values = manual_values(load_catalog(root / CATALOG_RELATIVE))
    secrets_dir = root / SECRETS_RELATIVE
    secrets_dir.mkdir(parents=True, exist_ok=True)
    for key, value in values.items():
        (secrets_dir / key).write_text(value)
    return len(values), secrets_dir


def main() -> int:
    try:
        written, secrets_dir = preseed(REPO_ROOT)
    except CatalogError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    print(f"Pre-seeded {written} manual secrets in {secrets_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
