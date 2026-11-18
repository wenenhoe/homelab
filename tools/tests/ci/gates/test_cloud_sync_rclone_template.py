"""cloud_sync's rclone config skips the bucket pre-flight check on each upload target, whose keys are bucket-restricted."""

from __future__ import annotations

import configparser
from pathlib import Path

import jinja2

TEMPLATE = Path(__file__).resolve().parents[4] / "ansible/roles/cloud_sync/templates/rclone.conf.j2"


def render() -> configparser.ConfigParser:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)  # noqa: S701 - an rclone config, not HTML
    text = env.from_string(TEMPLATE.read_text()).render(
        seaweedfs_cloud_sync_reader_access_key="reader-ak",
        seaweedfs_cloud_sync_reader_secret_key="reader-sk",
        seaweedfs_s3_proto="http",
        seaweedfs_s3_endpoint="seaweedfs:8333",
        cloud_sync_targets={
            "target_a": {"access_key": "a-ak", "secret_key": "a-sk", "endpoint": "https://a.example", "region": "us-east-1"},
            "target_b": {"access_key": "b-ak", "secret_key": "b-sk", "endpoint": "https://b.example"},
        },
    )
    parser = configparser.ConfigParser()
    parser.read_string(text)
    return parser


def test_every_upload_target_skips_the_bucket_preflight_check() -> None:
    config = render()

    assert [config[target]["no_check_bucket"] for target in ("target_a", "target_b")] == ["true", "true"]


def test_the_source_remote_is_left_as_it_was() -> None:
    assert "no_check_bucket" not in render()["seaweedfs"]
