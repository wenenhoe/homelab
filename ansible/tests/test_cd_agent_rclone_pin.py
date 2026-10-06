"""The CD agent's native rclone is on the minor release cloud_sync's image runs.

Leaf-key verification has to follow the request sequence production's rclone
makes (docs/topics/secrets/cloud-credentials/rotation.md), so a native rclone
from another minor release could accept a key production's would reject.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROLES = Path(__file__).resolve().parents[1] / "roles"


def _pins() -> dict[str, str]:
    return yaml.safe_load((ROLES / "cd_agent/defaults/main.yaml").read_text())


def test_native_rclone_is_on_the_minor_release_cloud_sync_runs():
    unit = (ROLES / "cloud_sync/templates/cloud-sync.service.j2").read_text()
    image_tag = re.search(r"rclone/rclone:(\d+\.\d+)\b", unit)

    assert image_tag, "cloud_sync's unit no longer pins an rclone/rclone image as <major>.<minor>"
    assert _pins()["cd_agent_rclone_version"].startswith(f"{image_tag.group(1)}.")


def test_the_pinned_checksum_is_a_sha256():
    assert re.fullmatch(r"[0-9a-f]{64}", _pins()["cd_agent_rclone_sha256"])
