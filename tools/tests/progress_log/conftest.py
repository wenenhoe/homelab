"""Fixtures for the progress log tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from _progress_fixtures import Repo


@pytest.fixture
def repo(tmp_path_factory: pytest.TempPathFactory) -> Repo:
    return Repo(tmp_path_factory.mktemp("repo"))


@pytest.fixture
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The directory the log is written to, standing in for a checkout of the progress-log branch."""
    return tmp_path_factory.mktemp("log")
