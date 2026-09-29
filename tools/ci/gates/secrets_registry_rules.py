#!/usr/bin/env python3
"""Checks that every entry in secrets_registry.yaml follows the rules its header comment states.

A wrong combination otherwise surfaces at deploy or rotation time: a hex entry
with no `vault_scope` is silently skipped by the `secrets` role, and a mistyped
key on a manual entry moves it to the file cache. Each violation is reported
with the entry's name and the rule it breaks; any violation fails the check.

Runs in pre-commit (PyYAML only) and so in the pre-commit-checks job.

Usage (from tools/): python -m ci.gates.secrets_registry_rules
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from utils.secrets_registry import REGISTRY_PATH, Registry, RegistryError, load_registry

FORMATS = ("hex", "uuid4", "manual")
KEYS = frozenset({"format", "length", "vault_scope", "description", "allow_blank", "sensitive"})
MANUAL_ONLY_FLAGS = ("allow_blank", "sensitive")

KEBAB_CASE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
# The header's three shapes: a host, a concern shared by every host, and the cloud-credential leaf keys.
SCOPE = re.compile(r"hosts/(security|services|storage|play)|hosts/all/[a-z0-9]+(-[a-z0-9]+)*|cloud_credentials/leaf")


@dataclass(frozen=True)
class Violation:
    name: str
    rule: str
    message: str


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_entry(name: str, spec: dict[str, object]) -> list[Violation]:
    found: list[Violation] = []

    def fail(rule: str, message: str) -> None:
        found.append(Violation(name, rule, message))

    if not KEBAB_CASE.fullmatch(name):
        fail("name", "names are kebab-case: lowercase letters and digits separated by single hyphens")
    for key in sorted(set(spec) - KEYS):
        fail("unknown-key", f"`{key}` isn't a registry key (one of: {', '.join(sorted(KEYS))})")

    fmt = spec.get("format")
    if fmt not in FORMATS:
        fail("format", f"`format` must be one of {', '.join(FORMATS)}, not {fmt!r}")

    if fmt == "hex" and not _is_positive_int(spec.get("length")):
        fail("length-required", "`format: hex` requires `length`, a positive integer")
    if fmt in ("uuid4", "manual") and "length" in spec:
        fail("length-forbidden", f"`length` applies only to `format: hex`, not `format: {fmt}`")

    if fmt in ("hex", "uuid4") and "vault_scope" not in spec:
        fail("scope-required", f"`format: {fmt}` requires `vault_scope`: Ansible can only generate into OpenBao")
    if "vault_scope" in spec and not (isinstance(spec["vault_scope"], str) and SCOPE.fullmatch(spec["vault_scope"])):
        fail(
            "scope-shape",
            f"`vault_scope` must be hosts/<security|services|storage|play>, hosts/all/<concern> or cloud_credentials/leaf, not {spec['vault_scope']!r}",
        )

    if fmt == "manual" and not _is_text(spec.get("description")):
        fail("description-required", "`format: manual` requires a non-empty `description`: it is what a missing secret's error shows")

    for flag in MANUAL_ONLY_FLAGS:
        if flag not in spec:
            continue
        if fmt != "manual":
            fail("flag-manual-only", f"`{flag}` is valid only on `format: manual`")
        elif not isinstance(spec[flag], bool):
            fail("flag-boolean", f"`{flag}` must be true or false, not {spec[flag]!r}")
    return found


def validate(registry: Registry) -> list[Violation]:
    """Every rule violation in `registry`, in entry order."""
    return [violation for name, spec in registry.items() for violation in _check_entry(name, spec)]


def main() -> int:
    try:
        violations = validate(load_registry(REGISTRY_PATH))
    except RegistryError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for violation in violations:
        print(f"::error::{violation.name}: {violation.message} [{violation.rule}]", file=sys.stderr)
    if violations:
        print(f"{len(violations)} rule violation(s) in the secrets registry", file=sys.stderr)
        return 1
    print("secrets_registry.yaml: every entry follows the header's rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
