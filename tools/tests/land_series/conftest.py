"""Fixtures for the land_series tests."""

from __future__ import annotations

import pytest
from _series_repo import Author, Repo


@pytest.fixture
def repo(tmp_path_factory: pytest.TempPathFactory) -> Repo:
    """A repository whose `main` the layers are replayed on."""
    return Repo(tmp_path_factory.mktemp("repo"))


@pytest.fixture
def author(repo: Repo, tmp_path_factory: pytest.TempPathFactory) -> Author:
    return Author(repo, tmp_path_factory.mktemp("author") / "clone")
