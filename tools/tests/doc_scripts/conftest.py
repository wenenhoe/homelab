"""Fixtures for the doc_scripts tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An empty directory standing in for a repository root. Not `tmp_path`: that embeds the test's name in the path."""
    return tmp_path_factory.mktemp("tree")
