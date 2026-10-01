"""Tests for the fixtures in tools/tests/conftest.py."""

from __future__ import annotations

from utils import repo


def test_secrets_dir_starts_empty(secrets_dir):
    assert repo.read_bootstrap_file("main-domain") is None


def test_secrets_dir_serves_seeded_files_to_the_code_under_test(secrets_dir):
    secrets_dir.seed("main-domain", "  seeded.example \n")

    assert repo.read_bootstrap_file("main-domain") == "seeded.example"
    assert (secrets_dir.path / "main-domain").read_text() == "  seeded.example \n"


def test_secrets_dir_path_does_not_embed_the_test_name(secrets_dir, request):
    assert request.node.name[:20] not in str(secrets_dir.path)
