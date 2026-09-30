#!/usr/bin/env python3
"""Checks the invariants of the app catalog that a merge cannot enforce.

`resolve_apps` lays a host's entry over the catalog's; it never looks inside
either. A backup naming a volume the app doesn't declare, or a route with no
upstream, otherwise surfaces at deploy time, a repeated app name silently
replaces the first entry when the file is loaded, a route map under the
old `caddy` key is ignored without an error, and so are cloud targets under
the old `backup.extra_cloud_targets` key. Each violation is reported
with the app's name and the rule it breaks; any violation fails the check.

Runs in pre-commit (PyYAML only) and so in the pre-commit-checks job.

Usage (from tools/): python -m ci.gates.app_catalog_rules
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from utils.app_catalog import CATALOG_PATH, CATALOG_RELATIVE, Catalog, CatalogError, load_catalog

ROUTES_KEY = "routes"
LEGACY_ROUTES_KEY = "caddy"
CLOUD_TARGETS_KEY = "cloud_targets"
LEGACY_CLOUD_TARGETS_KEY = "extra_cloud_targets"


@dataclass(frozen=True)
class Violation:
    name: str
    rule: str
    message: str


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


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
    elif backup is not None and backup.get("volumes") is not None:
        backed_up = backup["volumes"]
        if not (isinstance(backed_up, list) and all(_is_text(v) for v in backed_up)):
            fail("backup-shape", "`backup.volumes` must be a list of volume names")
        elif declared is not None:
            for volume in backed_up:
                if volume not in declared:
                    fail("backup-volume", f"`backup.volumes` names `{volume}`, which the app's `volumes` doesn't declare")

    if isinstance(backup, dict) and LEGACY_CLOUD_TARGETS_KEY in backup:
        fail(
            "legacy-cloud-targets-key",
            f"`backup.{LEGACY_CLOUD_TARGETS_KEY}` was renamed `backup.{CLOUD_TARGETS_KEY}`; the old key is ignored, so the app gets the defaults",
        )

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


def validate(catalog: Catalog) -> list[Violation]:
    """Every rule violation in `catalog`, in app order."""
    return [violation for name, app in catalog.items() for violation in _check_app(name, app)]


def main() -> int:
    try:
        violations = validate(load_catalog(CATALOG_PATH))
    except CatalogError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for violation in violations:
        print(f"::error::{violation.name}: {violation.message} [{violation.rule}]", file=sys.stderr)
    if violations:
        print(f"{len(violations)} rule violation(s) in {CATALOG_RELATIVE}", file=sys.stderr)
        return 1
    print(f"{CATALOG_RELATIVE}: every app follows the catalog rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
