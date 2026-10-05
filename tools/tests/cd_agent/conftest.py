"""Fixtures for the cd_agent tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from _origin import Origin
from cd_agent import run_job


@pytest.fixture
def origin(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Origin:
    """A repository on disk that the code under test fetches over `file` instead of `https`."""
    monkeypatch.setattr(run_job, "ALLOWED_SCHEME", "file")
    return Origin(tmp_path_factory.mktemp("origin"))


@pytest.fixture
def state_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("state") / "job"


@pytest.fixture
def log(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The file a job's command appends one line to per run; absent until a command runs."""
    path = tmp_path_factory.mktemp("log") / "runs.log"
    monkeypatch.setenv("CD_AGENT_TEST_LOG", str(path))
    return path
