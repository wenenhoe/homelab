"""Fixtures for the deliver_series tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from _delivery_repo import Workspace


@pytest.fixture(autouse=True)
def remote_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """The command runs only in a session that is thrown away, which this variable says."""
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")


@pytest.fixture
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Workspace:
    return Workspace(tmp_path_factory.mktemp("delivery"))


@pytest.fixture
def plan_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("plan") / "plan.txt"
