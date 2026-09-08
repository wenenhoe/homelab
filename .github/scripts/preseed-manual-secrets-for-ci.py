#!/usr/bin/env python3
"""Writes a throwaway dummy value to ansible/files/secrets/<key> for
every manual-format secrets_registry entry, for deploy-ordering-check's
own two ansible-playbook invocations — mirroring what
bootstrap_secrets.py would produce on a real first-ever deploy.

Driven off the real secrets_registry.yaml at CI-run time rather than a
hand-maintained list of printf lines in the workflow file: the previous
approach needed a new line added there every time a new manual secret
was registered, with nothing enforcing that it actually happened — this
can't drift, since it reads the exact same registry ensure_secret.yaml
itself reads.

allow_blank: true entries get an empty string — present-but-empty is
valid, not an error, for these (matches what a first-ever deploy looks
like before Beszel/Kuma/OpenBao's AppRole exist). Every other manual
entry gets a generic, traceable dummy value (ci-dummy-<key>).
deploy-ordering-check never validates any secret's actual content —
--tags filters out every provisioning play that would actually use
these values, so nothing here needs to look like a real domain,
API key, or numeric ID.

Usage:
    python3 .github/scripts/preseed-manual-secrets-for-ci.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "ansible/inventory/group_vars/all/secrets_registry.yaml"
SECRETS_DIR = ROOT / "ansible/files/secrets"


def main() -> int:
    with REGISTRY_PATH.open() as f:
        data = yaml.safe_load(f)

    SECRETS_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    for key, spec in data["secrets_registry"].items():
        if spec.get("format") != "manual":
            continue
        value = "" if spec.get("allow_blank") else f"ci-dummy-{key}"
        (SECRETS_DIR / key).write_text(value)
        written += 1

    print(f"Pre-seeded {written} manual secrets in {SECRETS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
