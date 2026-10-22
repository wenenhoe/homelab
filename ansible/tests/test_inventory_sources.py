"""ansible.cfg loads the inventory file and then the generated one, and everything that writes or passes it agrees."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

import restore_all
from tofu_inventory import generate

ANSIBLE_DIR = Path(__file__).resolve().parents[1]


def configured_sources() -> list[str]:
    config = ConfigParser(interpolation=None)
    config.read(ANSIBLE_DIR / "ansible.cfg")
    return config["defaults"]["inventory"].split(",")


def test_the_generated_inventory_loads_after_the_hand_written_one():
    # The later source wins, so a host's generated address replaces any left in inventory.yaml.
    assert configured_sources() == ["inventory/inventory.yaml", "inventory/tofu-hosts.yaml"]


def test_the_generator_writes_the_file_ansible_loads():
    assert ANSIBLE_DIR / configured_sources()[1] == generate.DEFAULT_OUT


def test_restore_all_passes_the_configured_sources_in_order():
    assert restore_all.INVENTORY_ARGS[1::2] == configured_sources()
    assert restore_all.INVENTORY_ARGS[0::2] == ["-i", "-i"]
