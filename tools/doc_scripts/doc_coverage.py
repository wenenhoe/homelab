"""The generated coverage view (ADR 0100): one row per catalog app with its hosts, volumes,
routes and their authentication, backup, service record and recovery tier. Rendered into
`docs/topics/disaster-recovery/coverage.md` by generate_doc_indexes.py and never hand-edited.

The view derives everything from the app catalog and the inventory. It shows no result of any exercise.
"""

from __future__ import annotations

import os
from pathlib import Path

from utils.app_catalog import CATALOG_RELATIVE, CatalogError, load_backup_inventory, load_catalog

from doc_scripts.doc_frontmatter import ROOT

COVERAGE_RELATIVE = "docs/topics/disaster-recovery/coverage.md"
INVENTORY_RELATIVE = "ansible/inventory"
HEADER = "| App | Hosts | Volumes | Routes | Backup | Record | Tier |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"


def tier_of(entry: dict) -> int:
    """1 when the catalog says so, else 2 for an app with a backup, else 3 (ADR 0101)."""
    if entry.get("recovery_tier") == 1:
        return 1
    return 2 if entry.get("backup") else 3


def _cell(values: list[str]) -> str:
    return ", ".join(values) if values else "—"


def render_coverage_table(root: Path = ROOT) -> str:
    try:
        catalog = load_catalog(root / CATALOG_RELATIVE)
        inventory = load_backup_inventory(root / INVENTORY_RELATIVE)
    except CatalogError as exc:
        raise SystemExit(str(exc)) from exc
    default_cron = str(inventory.defaults.get("cron", "—"))
    view_dir = (root / COVERAGE_RELATIVE).parent
    rows = []
    for name, app in catalog.items():
        hosts = [host for host, entries in inventory.compose_apps.items() if any(e["name"] == name for e in entries)]
        volumes = [str(v["name"]) for v in app.get("volumes", []) if isinstance(v, dict) and "name" in v]
        routes = app.get("routes", {})
        route_cells = (
            [f"`{key}` ({'no Tinyauth' if isinstance(r, dict) and r.get('auth') is False else 'Tinyauth'})" for key, r in routes.items()]
            if isinstance(routes, dict)
            else []
        )
        backup = app.get("backup")
        if isinstance(backup, dict):
            cron = str(backup.get("cron", default_cron))
            backup_cell = f"{', '.join(map(str, backup.get('volumes', [])))} at `{cron}`"
        else:
            backup_cell = "—"
        doc = app.get("doc")
        record = f"[{Path(doc).name}]({os.path.relpath(root / doc, view_dir)})" if isinstance(doc, str) else "—"
        rows.append(f"| `{name}` | {_cell(hosts)} | {_cell([f'`{v}`' for v in volumes])} | {_cell(route_cells)} | {backup_cell} | {record} | {tier_of(app)} |")
    return "\n".join([HEADER, *rows])
