"""Fixtures shared across the tools/ test directories."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import create_autospec

import hvac
import paramiko
import pytest
import requests
from _hvac_clients import stubbed_hvac_client
from _sessions import stubbed_session
from _ssh_objects import stubbed_ssh_client


class SecretsDir:
    def __init__(self, path: Path) -> None:
        self.path = path

    def seed(self, name: str, value: str) -> None:
        (self.path / name).write_text(value)


@pytest.fixture
def secrets_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> SecretsDir:
    """An empty stand-in for utils.repo.SECRETS_DIR, where main-domain and the AppRole files are always read from.

    Not `tmp_path`: that embeds the test's name in the path, and error messages quote the path, so a `match=` regex
    can pass on the path instead of the message.
    """
    from utils import repo

    path = tmp_path_factory.mktemp("secrets")
    monkeypatch.setattr(repo, "SECRETS_DIR", path)
    return SecretsDir(path)


@pytest.fixture
def http_session() -> requests.Session:
    """A real `requests.Session` with its network calls stubbed (see `_sessions.py`)."""
    return stubbed_session()


@pytest.fixture
def session_class(http_session: requests.Session, monkeypatch: pytest.MonkeyPatch) -> object:
    """`requests.Session` replaced, for every module, by a class bound to the real constructor that returns `http_session`."""
    cls = create_autospec(requests.Session, return_value=http_session)
    monkeypatch.setattr(requests, "Session", cls)
    return cls


@pytest.fixture
def hvac_client() -> hvac.Client:
    """A real `hvac.Client` with its network calls stubbed (see `_hvac_clients.py`)."""
    return stubbed_hvac_client()


@pytest.fixture
def ssh_client() -> paramiko.SSHClient:
    """A real `paramiko.SSHClient` with its network and file calls stubbed (see `_ssh_objects.py`)."""
    return stubbed_ssh_client()
