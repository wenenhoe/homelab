"""The generated coverage view (ADR 0100): one row per catalog app with its hosts, volumes,
routes and their authentication, backup, service record, and the newest fire drill that
restored it. Rendered into `docs/topics/disaster-recovery/coverage.md` by generate_doc_indexes.py
and never hand-edited.

The drill column reads the "Apps covered" cell of the fire-drill results table. Each
comma-separated item there is a catalog key in any case, with an optional parenthetical, or
`None` for a drill that restored no app. An item that matches neither fails the generation, so a
renamed or misspelled app cannot silently drop out of the view.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from utils.app_catalog import CATALOG_RELATIVE, CatalogError, load_backup_inventory, load_catalog

from doc_scripts.doc_frontmatter import ROOT

COVERAGE_RELATIVE = "docs/topics/disaster-recovery/coverage.md"
FIRE_DRILL_RELATIVE = "docs/topics/disaster-recovery/fire-drill.md"
INVENTORY_RELATIVE = "ansible/inventory"
NO_APP = "none"
DRILL_ROW_RE = re.compile(r"^\| (\d{4}-\d{2}-\d{2}) \| (.*?) \| ", re.MULTILINE)
HEADER = "| App | Hosts | Volumes | Routes | Backup | Record | Newest restoring drill |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"


def split_items(cell: str) -> list[str]:
    """The comma-separated items of a cell, leaving commas inside parentheses alone."""
    items, depth, current = [], 0, []
    for char in cell:
        depth += char == "("
        depth -= char == ")" and depth > 0
        if char == "," and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))
    return [item.strip() for item in items if item.strip()]


def item_name(item: str) -> str:
    """The name part of an item: lower-cased, backticks removed, any trailing parenthetical dropped."""
    return re.sub(r"\s*\(.*\)\s*$", "", item).replace("`", "").strip().lower()


def drill_dates(text: str, keys: set[str]) -> dict[str, str]:
    """App key -> the date of the newest fire-drill row that lists it. A name that is neither a key nor `None` raises."""
    newest: dict[str, str] = {}
    unknown: list[str] = []
    for date, cell in DRILL_ROW_RE.findall(text):
        for item in split_items(cell):
            name = item_name(item)
            if name in keys:
                newest[name] = max(date, newest.get(name, date))
            elif name != NO_APP:
                unknown.append(f"{date}: {item}")
    if unknown:
        raise SystemExit("the fire-drill table's 'Apps covered' column must hold catalog app keys or `None`; no key matches: " + "; ".join(unknown))
    return newest


def _cell(values: list[str]) -> str:
    return ", ".join(values) if values else "—"


def render_coverage_table(root: Path = ROOT) -> str:
    try:
        catalog = load_catalog(root / CATALOG_RELATIVE)
        inventory = load_backup_inventory(root / INVENTORY_RELATIVE)
    except CatalogError as exc:
        raise SystemExit(str(exc)) from exc
    default_cron = str(inventory.defaults.get("cron", "—"))
    dates = drill_dates((root / FIRE_DRILL_RELATIVE).read_text(encoding="utf-8"), set(catalog))
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
        rows.append(
            f"| `{name}` | {_cell(hosts)} | {_cell([f'`{v}`' for v in volumes])} | {_cell(route_cells)} | {backup_cell} | {record} | {dates.get(name, '—')} |"
        )
    return "\n".join([HEADER, *rows])
