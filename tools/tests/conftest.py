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
def secrets_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SecretsDir:
    """An empty stand-in for utils.repo.SECRETS_DIR, where main-domain and the AppRole files are always read from."""
    from utils import repo

    monkeypatch.setattr(repo, "SECRETS_DIR", tmp_path)
    return SecretsDir(tmp_path)
