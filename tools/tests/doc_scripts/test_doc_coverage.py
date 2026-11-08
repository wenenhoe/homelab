"""Unit tests for doc_coverage.py: the generated coverage view of ADR 0100. Run via `uv run pytest tools/tests/ -v`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from doc_scripts import doc_coverage as coverage

CATALOG = {
    "alpha": {
        "volumes": [{"name": "data"}],
        "backup": {"volumes": ["data"]},
        "routes": {"default": {"upstream": "alpha:1"}},
        "doc": "docs/topics/services/alpha.md",
    },
    "beta": {
        "volumes": [{"name": "cfg"}, {"name": "db"}],
        "backup": {"volumes": ["db"], "cron": "0 1 * * *"},
        "routes": {"s3": {"upstream": "beta:2", "auth": False}},
    },
    "gamma": {},
}
DRILLS = """| Date | Apps covered | Result |
| :--- | :--- | :--- |
| 2026-01-01 | alpha | Pass |
| 2026-02-01 | Alpha (data only), `beta` | Pass |
| 2026-03-01 | None (the bucket was copied, no app restored) | Pass |
"""


def tree(tmp_path: Path, drills: str = DRILLS) -> Path:
    inventory = tmp_path / "ansible/inventory"
    (inventory / "group_vars/all").mkdir(parents=True)
    (inventory / "host_vars").mkdir()
    (inventory / "group_vars/all/app_catalog.yaml").write_text(yaml.safe_dump({"app_catalog": CATALOG}, sort_keys=False))
    (inventory / "group_vars/all/main.yaml").write_text(yaml.safe_dump({"backup_defaults": {"cron": "30 4 * * *"}}))
    (inventory / "group_vars/all/secret_catalog.yaml").write_text(yaml.safe_dump({"secret_catalog": {}}))
    (inventory / "inventory.yaml").write_text(yaml.safe_dump({"all": {"children": {"managed_hosts": {"hosts": {"h1": {}, "storage": {}}}}}}))
    (inventory / "host_vars/h1.yaml").write_text(yaml.safe_dump({"compose_apps": [{"name": "alpha"}]}))
    (inventory / "host_vars/storage.yaml").write_text(yaml.safe_dump({"cloud_sync_targets": {}, "compose_apps": [{"name": "alpha"}, {"name": "beta"}]}))
    drill = tmp_path / coverage.FIRE_DRILL_RELATIVE
    drill.parent.mkdir(parents=True)
    drill.write_text(drills)
    return tmp_path


def rows(tmp_path: Path, drills: str = DRILLS) -> dict[str, list[str]]:
    lines = coverage.render_coverage_table(tree(tmp_path, drills)).splitlines()[2:]
    return {line.split("|")[1].strip(" `"): [c.strip() for c in line.split("|")[2:-1]] for line in lines}


def test_each_catalog_app_gets_a_row_with_its_hosts_volumes_routes_and_backup(tmp_path: Path) -> None:
    got = rows(tmp_path)
    assert list(got) == ["alpha", "beta", "gamma"]
    assert got["alpha"][:4] == ["h1, storage", "`data`", "`default` (Tinyauth)", "data at `30 4 * * *`"]
    assert got["beta"][:4] == ["storage", "`cfg`, `db`", "`s3` (no Tinyauth)", "db at `0 1 * * *`"]
    assert got["gamma"] == ["—", "—", "—", "—", "—", "—"]


def test_the_record_is_a_link_relative_to_the_view(tmp_path: Path) -> None:
    assert rows(tmp_path)["alpha"][4] == "[alpha.md](../services/alpha.md)"


def test_the_drill_column_is_the_newest_date_naming_the_app_in_any_case_with_a_parenthetical(tmp_path: Path) -> None:
    got = rows(tmp_path)
    assert got["alpha"][5] == "2026-02-01"
    assert got["beta"][5] == "2026-02-01"
    assert got["gamma"][5] == "—"


def test_none_marks_a_drill_that_restored_no_app_and_commas_inside_parentheses_are_not_separators(tmp_path: Path) -> None:
    assert coverage.split_items("None (a, b, c), alpha") == ["None (a, b, c)", "alpha"]
    assert rows(tmp_path)["gamma"][5] == "—"


def test_a_name_that_matches_no_app_fails_the_generation(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match=r"2026-04-01: delta"):
        rows(tmp_path, DRILLS + "| 2026-04-01 | delta | Pass |\n")


def test_the_output_is_the_same_on_a_second_run(tmp_path: Path) -> None:
    root = tree(tmp_path)
    assert coverage.render_coverage_table(root) == coverage.render_coverage_table(root)
