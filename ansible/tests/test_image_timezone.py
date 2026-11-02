"""The timezone baked into every VM's image is the one the containers take as TZ."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_DIR = Path(__file__).resolve().parents[2]


def test_the_images_timezone_is_the_inventorys_server_timezone():
    variables = (REPO_DIR / "tofu/variables.tf").read_text()
    block = re.search(r'variable "timezone" \{.*?default\s*=\s*"([^"]+)"', variables, re.DOTALL)
    assert block, "tofu/variables.tf has no timezone variable with a default"
    inventory = yaml.safe_load((REPO_DIR / "ansible/inventory/group_vars/all/main.yaml").read_text())
    assert block.group(1) == inventory["server_timezone"]
