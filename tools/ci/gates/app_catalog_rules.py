#!/usr/bin/env python3
"""Checks the invariants of the app catalog that a merge cannot enforce.

`resolve_apps` lays a host's entry over the catalog's; it never looks inside
either. A backup naming a volume the app doesn't declare, or a route with no
upstream, otherwise surfaces at deploy time, a repeated app name silently
replaces the first entry when the file is loaded, a route map under the
old `caddy` key is ignored without an error, and so are cloud targets under
the old `backup.extra_cloud_targets` key. A `backup` block has to name
volumes, keep each setting in its shape and use only backup keys (in the catalog,
in a host's own override and in `backup_defaults`: the plan ignores a misspelt
one without a word), and, against the inventory (ADR
0068), every cloud target it or `backup_defaults` names has to be defined in
`cloud_sync_targets` and every host that runs a backed-up app has to have its
own SeaweedFS secret pair and host variables, or the deploy fails late on an
undefined variable. Each violation is reported with the app's (or host's) name
and the rule it breaks; any violation fails the check.

Runs in pre-commit (PyYAML only) and so in the pre-commit-checks job. The
inventory is read as plain YAML; no value is rendered.

Usage (from tools/): python -m ci.gates.app_catalog_rules
"""

from __future__ import annotations

import difflib
import sys
from dataclasses import dataclass

from utils.app_catalog import CATALOG_PATH, CATALOG_RELATIVE, BackupInventory, Catalog, CatalogError, load_backup_inventory, load_catalog

ROUTES_KEY = "routes"
LEGACY_ROUTES_KEY = "caddy"
CLOUD_TARGETS_KEY = "cloud_targets"
LEGACY_CLOUD_TARGETS_KEY = "extra_cloud_targets"
DEFAULTS_NAME = "backup_defaults"
# The keys of an app's `backup:` block that have a default, which are the keys of backup_defaults. The
# backup_plan filter in ansible/filter_plugins/ keeps the same list; a test holds the two equal.
BACKUP_SETTINGS = ("cron", "retention_days", "compression", "stop_during_backup", "cloud_targets")
COMPRESSIONS = ("gz", "zst", "none")
BACKUP_KEYS = ("volumes", *BACKUP_SETTINGS)


@dataclass(frozen=True)
class Violation:
    name: str
    rule: str
    message: str


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _setting_problems(block: dict[str, object], prefix: str) -> list[str]:
    """What is wrong with the shape of each backup setting `block` sets, named `prefix.key`."""
    problems = []
    targets = block.get(CLOUD_TARGETS_KEY)
    if CLOUD_TARGETS_KEY in block and not (isinstance(targets, list) and all(_is_text(t) for t in targets)):
        problems.append(f"`{prefix}.{CLOUD_TARGETS_KEY}` must be a list of cloud target names")
    days = block.get("retention_days")
    if "retention_days" in block and not (isinstance(days, int) and not isinstance(days, bool) and days > 0):
        problems.append(f"`{prefix}.retention_days` must be a positive integer")
    if "compression" in block and block["compression"] not in COMPRESSIONS:
        problems.append(f"`{prefix}.compression` must be one of {', '.join(COMPRESSIONS)}")
    if "stop_during_backup" in block and not isinstance(block["stop_during_backup"], bool):
        problems.append(f"`{prefix}.stop_during_backup` must be true or false")
    if "cron" in block and not _is_text(block["cron"]):
        problems.append(f"`{prefix}.cron` must be a non-empty string")
    return problems


def _key_problems(block: dict[object, object], prefix: str, allowed: tuple[str, ...]) -> list[tuple[str, str]]:
    """(rule, message) for each key of `block` that is not one of `allowed`; the plan ignores such a key without a word."""
    problems = []
    for key in block:
        if key == LEGACY_CLOUD_TARGETS_KEY:
            problems.append(("legacy-cloud-targets-key", f"`{prefix}.{key}` was renamed `{prefix}.{CLOUD_TARGETS_KEY}`; the old key is ignored"))
        elif key not in allowed:
            close = difflib.get_close_matches(str(key), allowed, n=1)
            hint = f" (did you mean `{close[0]}`?)" if close else ""
            problems.append(("backup-unknown-key", f"`{prefix}.{key}` isn't a backup setting; the keys are {', '.join(allowed)}{hint}"))
    return problems


def _check_app(name: str, app: dict[str, object]) -> list[Violation]:
    found: list[Violation] = []

    def fail(rule: str, message: str) -> None:
        found.append(Violation(name, rule, message))

    declared: set[str] | None = set()
    volumes = app.get("volumes")
    if volumes is not None:
        if isinstance(volumes, list) and all(isinstance(v, dict) and _is_text(v.get("name")) for v in volumes):
            declared = {v["name"] for v in volumes}
        else:
            declared = None
            fail("volumes-shape", "`volumes` must be a list of mappings that each have a `name`")

    backup = app.get("backup")
    if backup is not None and not isinstance(backup, dict):
        fail("backup-shape", "`backup` must be a mapping")
    elif isinstance(backup, dict):
        backed_up = backup.get("volumes")
        if backed_up is None or backed_up == []:
            fail("backup-volumes", "a `backup` block must name at least one volume; leave the block out for an app with nothing to back up")
        elif not (isinstance(backed_up, list) and all(_is_text(v) for v in backed_up)):
            fail("backup-shape", "`backup.volumes` must be a list of volume names")
        elif declared is not None:
            for volume in backed_up:
                if volume not in declared:
                    fail("backup-volume", f"`backup.volumes` names `{volume}`, which the app's `volumes` doesn't declare")
        for problem in _setting_problems(backup, "backup"):
            fail("backup-shape", problem)

    if isinstance(backup, dict):
        for rule, problem in _key_problems(backup, "backup", BACKUP_KEYS):
            fail(rule, problem)

    legacy = app.get(LEGACY_ROUTES_KEY)
    if isinstance(legacy, dict) and legacy and all(isinstance(route, dict) for route in legacy.values()):
        fail("legacy-route-key", f"`{LEGACY_ROUTES_KEY}` was renamed `{ROUTES_KEY}`; an app that still uses it silently has no routes")

    routes = app.get(ROUTES_KEY)
    if routes is not None and not isinstance(routes, dict):
        fail("routes-shape", f"`{ROUTES_KEY}` must be a mapping of route id -> route")
    elif routes is not None:
        for route_id, route in routes.items():
            if not isinstance(route, dict):
                fail("routes-shape", f"route `{route_id}` must be a mapping")
            elif not _is_text(route.get("upstream")):
                fail("route-upstream", f"route `{route_id}` has no `upstream`")
    return found


def _is_list_of_text(value: object) -> bool:
    return isinstance(value, list) and all(_is_text(item) for item in value)


def _unknown_targets(targets: object, known: frozenset[str]) -> list[str]:
    return [target for target in targets if target not in known] if _is_list_of_text(targets) else []


def _check_cloud_targets(catalog: Catalog, inventory: BackupInventory) -> list[Violation]:
    """Every cloud target an app or the defaults name must be defined, with its credentials, on `storage`."""
    found = []
    for name, app in catalog.items():
        backup = app.get("backup")
        for target in _unknown_targets(backup.get(CLOUD_TARGETS_KEY) if isinstance(backup, dict) else None, inventory.cloud_targets):
            found.append(
                Violation(
                    name, "cloud-target", f"`backup.{CLOUD_TARGETS_KEY}` names `{target}`, which `cloud_sync_targets` in host_vars/storage.yaml doesn't define"
                )
            )
    for target in _unknown_targets(inventory.defaults.get(CLOUD_TARGETS_KEY), inventory.cloud_targets):
        found.append(
            Violation(
                DEFAULTS_NAME,
                "cloud-target",
                f"`{DEFAULTS_NAME}.{CLOUD_TARGETS_KEY}` names `{target}`, which `cloud_sync_targets` in host_vars/storage.yaml doesn't define",
            )
        )
    return found


def _check_defaults(inventory: BackupInventory) -> list[Violation]:
    """backup_defaults supplies every setting, in the shape an app's own block would."""
    defaults = inventory.defaults
    missing = [key for key in BACKUP_SETTINGS if key not in defaults]
    found = [Violation(DEFAULTS_NAME, "backup-shape", f"`{DEFAULTS_NAME}` has no {', '.join(f'`{key}`' for key in missing)}")] if missing else []
    found += [Violation(DEFAULTS_NAME, "backup-shape", problem) for problem in _setting_problems(defaults, DEFAULTS_NAME)]
    return found + [Violation(DEFAULTS_NAME, rule, problem) for rule, problem in _key_problems(defaults, DEFAULTS_NAME, BACKUP_SETTINGS)]


def _check_overrides(inventory: BackupInventory) -> list[Violation]:
    """A host entry may lay its own `backup:` over an app's; it keeps the same keys and shapes, and may empty `volumes`."""
    found = []
    for host in inventory.managed_hosts:
        for entry in inventory.compose_apps[host]:
            own, prefix = entry.get("backup"), f"{entry['name']}.backup"
            if own is None:
                continue
            if not isinstance(own, dict):
                found.append(Violation(host, "backup-shape", f"`{prefix}` must be a mapping"))
                continue
            volumes = own.get("volumes", [])
            if not _is_list_of_text(volumes):
                found.append(Violation(host, "backup-shape", f"`{prefix}.volumes` must be a list of volume names"))
            found += [Violation(host, "backup-shape", problem) for problem in _setting_problems(own, prefix)]
            found += [Violation(host, rule, problem) for rule, problem in _key_problems(own, prefix, BACKUP_KEYS)]
    return found


def _effective_volumes(entry: dict[str, object], catalog: Catalog) -> object:
    """An app's `backup.volumes` on one host: the host entry's own list replaces the catalog's, as resolve_apps merges them."""
    own = entry.get("backup", ...)
    if own is not ... and not isinstance(own, dict):
        return None
    if isinstance(own, dict) and "volumes" in own:
        return own["volumes"]
    backup = catalog.get(str(entry["name"]), {}).get("backup")
    return backup.get("volumes") if isinstance(backup, dict) else None


def backup_hosts(catalog: Catalog, inventory: BackupInventory) -> list[str]:
    """The managed hosts, in inventory order, that run at least one backed-up app: what `backup_hosts` is in Ansible."""
    return [
        host
        for host in inventory.managed_hosts
        if any(isinstance(volumes := _effective_volumes(entry, catalog), list) and volumes for entry in inventory.compose_apps[host])
    ]


def _check_backup_hosts(catalog: Catalog, inventory: BackupInventory) -> list[Violation]:
    """A host with a backed-up app is given its own SeaweedFS identity, built from a secret pair and two host vars."""
    found = []
    for host in backup_hosts(catalog, inventory):
        for kind in ("access", "secret"):
            secret = f"seaweedfs-s3-{kind}-key-{host}"
            entry = inventory.secrets.get(secret)
            if not (entry and entry.get("scope") == f"hosts/{host}"):
                found.append(
                    Violation(
                        host, "backup-host-credentials", f"`{host}` runs a backed-up app, so secret_catalog.yaml needs `{secret}` scoped to `hosts/{host}`"
                    )
                )
            var = f"seaweedfs_s3_{kind}_key"
            value = inventory.host_vars[host].get(var)
            if not (isinstance(value, str) and f"secrets_generated['{secret}']" in value):
                found.append(
                    Violation(
                        host,
                        "backup-host-credentials",
                        f"`{host}` runs a backed-up app, so host_vars/{host}.yaml needs `{var}` taken from `secrets_generated['{secret}']`",
                    )
                )
    return found


def validate(catalog: Catalog, inventory: BackupInventory | None = None) -> list[Violation]:
    """Every rule violation in `catalog`, in app order, then those that need the inventory if it is given."""
    found = [violation for name, app in catalog.items() for violation in _check_app(name, app)]
    if inventory is not None:
        found += _check_defaults(inventory) + _check_overrides(inventory) + _check_cloud_targets(catalog, inventory) + _check_backup_hosts(catalog, inventory)
    return found


def main() -> int:
    try:
        violations = validate(load_catalog(CATALOG_PATH), load_backup_inventory())
    except CatalogError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for violation in violations:
        print(f"::error::{violation.name}: {violation.message} [{violation.rule}]", file=sys.stderr)
    if violations:
        print(f"{len(violations)} rule violation(s) in {CATALOG_RELATIVE} or the inventory it is checked against", file=sys.stderr)
        return 1
    print(f"{CATALOG_RELATIVE}: every app follows the catalog rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
