"""The gateway's time zone is the one every other host of the lab takes."""

from __future__ import annotations

from pathlib import Path

import patch_config
import yaml

REPO_DIR = Path(__file__).resolve().parents[2]


def test_the_seeds_default_time_zone_is_the_inventorys_server_timezone():
    inventory = yaml.safe_load((REPO_DIR / "ansible/inventory/group_vars/all/main.yaml").read_text())

    assert inventory["server_timezone"] == patch_config.DEFAULT_TIMEZONE
