"""Unit tests for openbao_utils.dump.

Run via `uv run pytest tools/tests/ -v`. Exercises against fake
Vault reads and a real tmp filesystem - no real Vault, same reasoning
as test_restore.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from openbao_utils import dump


class _FakeModule:
    def __init__(self, value: str | None):
        self._value = value

    def read_cache(self, name: str) -> str | None:
        return self._value


@pytest.fixture
def tmp(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("dump")


class TestDumpCloudCredentials:
    def test_writes_present_values_with_owner_only_permissions(self, tmp):
        with patch.object(dump, "LEGACY_CACHE_KEYS", [("k", _FakeModule("secret-value"))]):
            written, blank = dump._dump_cloud_credentials(tmp)
        assert written == ["k"]
        assert blank == []
        dest = tmp / "k"
        assert dest.read_text() == "secret-value"
        assert dest.stat().st_mode & 0o777 == 0o600

    def test_reports_missing_value_as_blank_not_an_error(self, tmp):
        with patch.object(dump, "LEGACY_CACHE_KEYS", [("k", _FakeModule(None))]):
            written, blank = dump._dump_cloud_credentials(tmp)
        assert written == []
        assert blank == ["k"]
        assert not (tmp / "k").exists()


class TestDumpHostsScope:
    @pytest.fixture
    def catalog_file(self, tmp) -> Path:
        return tmp / "catalog.yaml"

    def test_skips_entries_stored_in_the_file_cache(self, tmp, catalog_file):
        catalog_file.write_text("secret_catalog:\n  no-scope-key:\n    source: manual\n    store: controller_file\n")
        dest = tmp / "out"
        dest.mkdir()
        with patch.object(dump, "CATALOG_PATH", catalog_file), patch.object(dump, "read_vault_path", return_value="v", autospec=True):
            written, blank = dump._dump_hosts_scope(dest)
        assert written == []
        assert blank == []

    def test_writes_scoped_entry_from_its_declared_path(self, tmp, catalog_file):
        catalog_file.write_text("secret_catalog:\n  telegram-token:\n    source: manual\n    store: openbao\n    scope: hosts/all/telegram\n")
        dest = tmp / "out"
        dest.mkdir()
        calls = []

        def fake_read(path: str) -> str | None:
            calls.append(path)
            return "the-token"

        with patch.object(dump, "CATALOG_PATH", catalog_file), patch.object(dump, "read_vault_path", side_effect=fake_read, autospec=True):
            written, _blank = dump._dump_hosts_scope(dest)

        assert written == ["telegram-token"]
        assert calls == ["hosts/all/telegram/telegram-token"]
        assert (dest / "telegram-token").read_text() == "the-token"


class TestMain:
    def test_creates_a_fresh_owner_only_directory_each_run(self, tmp):
        catalog_file = tmp / "catalog.yaml"
        catalog_file.write_text("secret_catalog:\n  no-scope-key:\n    source: manual\n    store: controller_file\n")
        with (
            patch.object(dump, "CATALOG_PATH", catalog_file),
            patch.object(dump, "LEGACY_CACHE_KEYS", []),
            patch.object(dump, "read_vault_path", return_value=None, autospec=True),
            patch.object(Path, "home", return_value=tmp, autospec=True),
        ):
            rc = dump.main()
        assert rc == 0
        backups = [p for p in tmp.iterdir() if p.name.startswith("secrets-backup-pre-reinit-")]
        assert len(backups) == 1
        assert backups[0].stat().st_mode & 0o777 == 0o700

    def test_counts_a_key_present_in_both_sources_once(self, tmp, capsys):
        catalog_file = tmp / "catalog.yaml"
        catalog_file.write_text(
            "secret_catalog:\n"
            "  shared-key:\n    source: manual\n    store: openbao\n    scope: cloud_credentials/leaf\n"
            "  hosts-key:\n    source: manual\n    store: openbao\n    scope: hosts/all/x\n"
        )
        with (
            patch.object(dump, "CATALOG_PATH", catalog_file),
            patch.object(dump, "LEGACY_CACHE_KEYS", [("shared-key", _FakeModule("v1")), ("cc-key", _FakeModule("v2"))]),
            patch.object(dump, "read_vault_path", return_value="v1", autospec=True),
            patch.object(Path, "home", return_value=tmp, autospec=True),
        ):
            dump.main()
        out = capsys.readouterr().out
        (backup,) = [p for p in tmp.iterdir() if p.name.startswith("secrets-backup-pre-reinit-")]
        assert len(list(backup.iterdir())) == 3
        assert "Backed up 3 distinct secrets" in out
        assert "1 keys are listed in both and written once" in out

    def test_refuses_to_clobber_an_existing_backup_directory(self, tmp):
        # _backup_dir() is timestamped, but exist_ok=False is the actual
        # guarantee - assert the real failure mode, not just that two
        # calls happen to get different timestamps.
        with patch.object(dump, "_backup_dir", return_value=tmp / "collision", autospec=True):
            (tmp / "collision").mkdir()
            catalog_file = tmp / "catalog.yaml"
            catalog_file.write_text("secret_catalog: {}\n")
            with (
                patch.object(dump, "CATALOG_PATH", catalog_file),
                patch.object(dump, "LEGACY_CACHE_KEYS", []),
                pytest.raises(FileExistsError),
            ):
                dump.main()
