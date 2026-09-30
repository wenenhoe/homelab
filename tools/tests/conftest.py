"""Fixtures shared across the tools/ test directories."""

from __future__ import annotations

from pathlib import Path

import pytest


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
