#!/usr/bin/env python3
"""Writes the Trivy config for the Ansible misconfiguration scan.

Two things it does that trivy-action has no first-class input for:

1. `misconfiguration.scanners` narrows the scan to the ansible scanner.
2. `ansible.playbooks` lists the playbooks. Trivy's own discovery only reads
   YAML files directly in the project root (non-recursive), so it never
   finds anything under a playbooks/ subdirectory and the scan would cover
   zero playbooks without this list. The list is generated from the actual
   directory, so a new playbook is covered without a matching edit here.
   Import-only fragments like bootstrap-secrets.yaml are listed too: they
   are real .yaml files, and re-evaluating their tasks under their own entry
   is harmless.

The config is written at run time rather than committed so the secret-scan
job can't also auto-discover it if Trivy's cwd-based config lookup changes.
No playbooks found is an error: a scan that silently covers nothing is the
failure this list exists to prevent.

Usage (from tools/): python -m ci.scan.trivy_config <output-path>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ANSIBLE_DIR = "ansible"
PLAYBOOKS_DIR = "playbooks"


class NoPlaybooksError(Exception):
    """There is nothing for the scan to cover."""


def playbooks(root: Path) -> list[str]:
    """Playbook paths relative to ansible/: `*.yaml` first, then `*.yml`, each sorted."""
    directory = root / ANSIBLE_DIR / PLAYBOOKS_DIR
    found = [f"{PLAYBOOKS_DIR}/{path.name}" for suffix in (".yaml", ".yml") for path in sorted(directory.glob(f"*{suffix}")) if path.is_file()]
    if not found:
        raise NoPlaybooksError(f"no playbooks under {ANSIBLE_DIR}/{PLAYBOOKS_DIR}/; the scan would cover nothing")
    return found


def render(paths: list[str]) -> str:
    """The config as YAML text. json.dumps gives a valid double-quoted YAML string."""
    lines = ["misconfiguration:", "  scanners:", "    - ansible", "ansible:", "  playbooks:"]
    lines += [f"    - {json.dumps(path)}" for path in paths]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("output")
    args = parser.parse_args(argv)
    try:
        text = render(playbooks(REPO_ROOT))
    except NoPlaybooksError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    Path(args.output).write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
