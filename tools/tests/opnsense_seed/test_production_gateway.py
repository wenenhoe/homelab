"""The root module's production gateway and the pins the scratch gateway rehearses it with must agree."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
ROOT_FILE = (REPO / "tofu/opnsense.tf").read_text()
PIN = yaml.safe_load((REPO / "tofu/scratch/opnsense/image-pin.yaml").read_text())


def default_of(variable: str) -> str:
    match = re.search(rf'variable "{variable}" \{{.*?default\s*=\s*"([^"]*)"', ROOT_FILE, re.DOTALL)
    assert match, f"no default for {variable}"
    return match.group(1)


def test_the_production_gateway_boots_the_release_the_scratch_gateway_rehearses():
    expected = f"OPNsense-{PIN['version']}-nano-amd64.raw"

    assert default_of("opnsense_image_volume_id").endswith(f":import/{expected}")


def test_the_gateway_is_created_stopped_and_keeps_vmid_201_and_the_name_the_seed_derives_its_host_name_from():
    assert re.search(r"\bvm_id\s*=\s*201\b", ROOT_FILE)
    assert re.search(r"\bstarted\s*=\s*false\b", ROOT_FILE)
    assert re.search(r'\bname\s*=\s*"OPNsense"', ROOT_FILE)
