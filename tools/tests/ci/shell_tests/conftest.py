"""Fixtures for the shell-test pin tests."""

from __future__ import annotations

import pytest
from _git_repos import Remote


@pytest.fixture
def remote(tmp_path_factory: pytest.TempPathFactory) -> Remote:
    return Remote(tmp_path_factory.mktemp("remote"))
