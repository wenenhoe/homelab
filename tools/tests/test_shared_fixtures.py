"""Tests for the fixtures in tools/tests/conftest.py."""

from __future__ import annotations

from utils import repo


def test_secrets_dir_starts_empty(secrets_dir):
    assert repo.read_bootstrap_file("main-domain") is None


def test_secrets_dir_serves_seeded_files_to_the_code_under_test(secrets_dir):
    secrets_dir.seed("main-domain", "  seeded.example \n")

    assert repo.read_bootstrap_file("main-domain") == "seeded.example"
    assert (secrets_dir.path / "main-domain").read_text() == "  seeded.example \n"
