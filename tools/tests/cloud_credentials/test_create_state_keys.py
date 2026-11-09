"""Unit tests for cloud_credentials.create_state_keys.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from _b2_objects import bucket, full_application_key
from _responses import response
from cloud_credentials import create_state_keys as state

R2_GROUPS = {"Workers R2 Storage Bucket Item Write": "grp-write"}


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def backend_env() -> Path:
    return state.config_dir() / state.BACKEND_ENV


def copy_env() -> Path:
    return state.config_dir() / state.COPY_ENV


class TestEncryptionConfig:
    def test_steady_state_is_enforced_for_state_and_plan_and_has_no_plaintext_fallback(self):
        config = state.encryption_config("a-passphrase-of-16+")

        assert config.count("enforced = true") == 2
        assert "fallback" not in config
        assert "unencrypted" not in config
        assert 'passphrase = "a-passphrase-of-16+"' in config

    def test_migrating_adds_only_a_state_fallback_so_one_plaintext_read_is_possible(self):
        config = state.encryption_config("a-passphrase-of-16+", migrating=True)

        assert 'method "unencrypted" "migrate" {}' in config
        assert config.count("fallback") == 1
        assert "enforced" not in config, "an enforced block refuses the plaintext the fallback exists to read"


class TestEnvFile:
    def test_is_private_and_round_trips_values_with_quotes_newlines_and_shell_characters(self):
        values = {"PLAIN": "abc", "HCL": 'a "quoted" {\n  line = "two"\n}\n', "ODD": "x$y`z'w;q"}

        state.write_env_file(backend_env(), values)

        assert stat.S_IMODE(backend_env().stat().st_mode) == 0o600
        assert stat.S_IMODE(backend_env().parent.stat().st_mode) == 0o700
        assert state.read_env_file(backend_env()) == values

    def test_is_sourced_by_a_shell_to_the_same_values(self):
        values = {"TF_ENCRYPTION": state.encryption_config("a-passphrase-of-16+"), "AWS_SECRET_ACCESS_KEY": "s3cr$t`;'x"}
        state.write_env_file(backend_env(), values)

        out = subprocess.run(
            ["bash", "-c", f'. "{backend_env()}"; printf %s "$TF_ENCRYPTION"; printf "\\0%s" "$AWS_SECRET_ACCESS_KEY"'],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        assert out.split("\0") == [values["TF_ENCRYPTION"], values["AWS_SECRET_ACCESS_KEY"]]

    def test_replaces_the_file_whole_and_leaves_no_temp_files(self):
        state.write_env_file(backend_env(), {"A": "1"})
        state.write_env_file(backend_env(), {"A": "2"})

        assert state.read_env_file(backend_env()) == {"A": "2"}
        assert [p.name for p in backend_env().parent.iterdir()] == [state.BACKEND_ENV]

    def test_a_missing_file_reads_as_empty(self):
        assert state.read_env_file(backend_env()) == {}


class TestMintR2:
    @pytest.fixture(autouse=True)
    def _seeded(self, vault):
        vault.seed("_rotation-key-cloudflare-r2-token", "admin-token", category="rotation")
        vault.seed("cloudflare-r2-account-id", "acct123")

    @patch.object(state, "verify_leaf_via_rclone", return_value=(True, "PutObject succeeded"), autospec=True)
    @patch.object(state, "r2_permission_group_ids", return_value=R2_GROUPS, autospec=True)
    def test_mints_a_state_bucket_token_with_quarterly_expiry_and_writes_the_backend_env(self, _groups, mock_verify, session_class, capsys, vault, fake_vault):
        session = session_class.return_value
        session.post.return_value = response(json_body={"success": True, "result": {"id": "TOKEN_ID", "value": "token-value"}})

        assert state.mint_r2()

        body = session.post.call_args.kwargs["json"]
        assert f"acct123_default_{state.STATE_BUCKET_R2}" in next(iter(body["policies"][0]["resources"]))
        assert "expires_on" in body
        assert body["name"] == state.TOKEN_NAME_R2
        secret = state.hashlib.sha256(b"token-value").hexdigest()
        mock_verify.assert_called_once_with("TOKEN_ID", secret, "https://acct123.r2.cloudflarestorage.com", "auto", state.STATE_BUCKET_R2, "write")

        env = state.read_env_file(backend_env())
        assert env["AWS_ACCESS_KEY_ID"] == "TOKEN_ID"
        assert env["AWS_SECRET_ACCESS_KEY"] == secret
        assert env["AWS_ENDPOINT_URL_S3"] == "https://acct123.r2.cloudflarestorage.com"
        assert env["TF_ENCRYPTION"] == state.encryption_config(env["TOFU_STATE_PASSPHRASE"])
        assert env["TOFU_STATE_ENCRYPTION_MIGRATING"] == state.encryption_config(env["TOFU_STATE_PASSPHRASE"], migrating=True)
        assert len(env["TOFU_STATE_PASSPHRASE"]) >= 16, "OpenTofu's pbkdf2 provider rejects shorter passphrases"
        assert env["TOFU_STATE_PASSPHRASE"] in capsys.readouterr().out, "the passphrase is shown once so its offline copy can be taken"
        assert vault.get(state.VAULT_NAME_R2_ACCESS) == "TOKEN_ID"
        assert secret not in fake_vault.store.values(), "only the ID is registered, never the secret"

    @patch.object(state, "verify_leaf_via_rclone", return_value=(False, "PutObject failed: AccessDenied"), autospec=True)
    @patch.object(state, "r2_permission_group_ids", return_value=R2_GROUPS, autospec=True)
    def test_writes_nothing_for_a_token_that_fails_verification(self, _groups, _verify, session_class, vault):
        session_class.return_value.post.return_value = response(json_body={"success": True, "result": {"id": "TOKEN_ID", "value": "token-value"}})

        assert not state.mint_r2()

        assert not backend_env().exists()
        assert vault.get(state.VAULT_NAME_R2_ACCESS) is None

    @patch.object(state, "verify_leaf_via_rclone", autospec=True)
    def test_skips_when_the_file_exists(self, mock_verify, session_class):
        state.write_env_file(backend_env(), {"AWS_ACCESS_KEY_ID": "existing"})

        assert state.mint_r2()

        session_class.return_value.post.assert_not_called()
        mock_verify.assert_not_called()
        assert state.read_env_file(backend_env()) == {"AWS_ACCESS_KEY_ID": "existing"}


class TestRotateR2:
    @pytest.fixture(autouse=True)
    def _seeded(self, vault):
        vault.seed("_rotation-key-cloudflare-r2-token", "admin-token", category="rotation")
        vault.seed("cloudflare-r2-account-id", "acct123")
        state.write_env_file(
            backend_env(),
            {"AWS_ACCESS_KEY_ID": "OLD_TOKEN_ID", "AWS_SECRET_ACCESS_KEY": "old-secret", "TOFU_STATE_PASSPHRASE": "the-original-passphrase"},
        )

    @patch.object(state, "r2_delete_token", autospec=True)
    @patch.object(state, "verify_leaf_via_rclone", return_value=(True, "PutObject succeeded"), autospec=True)
    @patch.object(state, "r2_permission_group_ids", return_value=R2_GROUPS, autospec=True)
    def test_swaps_the_key_keeps_the_passphrase_and_revokes_the_old_token_last(self, _groups, _verify, mock_delete, session_class, capsys, vault):
        session = session_class.return_value
        session.post.return_value = response(json_body={"success": True, "result": {"id": "NEW_TOKEN_ID", "value": "new-value"}})
        seen_at_revoke = {}
        registered_at_revoke = []
        mock_delete.side_effect = lambda *_: (
            seen_at_revoke.update(state.read_env_file(backend_env())),
            registered_at_revoke.append(vault.get(state.VAULT_NAME_R2_ACCESS)),
        )

        assert state.mint_r2(rotate=True)

        mock_delete.assert_called_once_with(session, "acct123", "OLD_TOKEN_ID")
        assert seen_at_revoke["AWS_ACCESS_KEY_ID"] == "NEW_TOKEN_ID", "the new key must be on disk before the old one is revoked"
        env = state.read_env_file(backend_env())
        assert env["TOFU_STATE_PASSPHRASE"] == "the-original-passphrase", "a new passphrase would strand every state object already written"
        assert "the-original-passphrase" not in capsys.readouterr().out
        assert registered_at_revoke == ["NEW_TOKEN_ID"], "the freshness check must already see the new ID when the old key goes"

    @patch.object(state, "r2_delete_token", autospec=True)
    @patch.object(state, "verify_leaf_via_rclone", return_value=(False, "PutObject failed: AccessDenied"), autospec=True)
    @patch.object(state, "r2_permission_group_ids", return_value=R2_GROUPS, autospec=True)
    def test_leaves_the_old_key_in_place_when_the_new_one_fails_verification(self, _groups, _verify, mock_delete, session_class, vault):
        vault.seed(state.VAULT_NAME_R2_ACCESS, "OLD_TOKEN_ID")
        session_class.return_value.post.return_value = response(json_body={"success": True, "result": {"id": "NEW_TOKEN_ID", "value": "new-value"}})

        assert not state.mint_r2(rotate=True)

        mock_delete.assert_not_called()
        assert vault.get(state.VAULT_NAME_R2_ACCESS) == "OLD_TOKEN_ID"
        assert state.read_env_file(backend_env())["AWS_ACCESS_KEY_ID"] == "OLD_TOKEN_ID"

    def test_refuses_when_there_is_nothing_to_rotate(self):
        backend_env().unlink()

        assert not state.mint_r2(rotate=True)


class TestMintB2:
    @pytest.fixture(autouse=True)
    def _seeded(self, vault):
        vault.seed("_rotation-key-backblaze-b2-key-id", "rot-id", category="rotation")
        vault.seed("_rotation-key-backblaze-b2-application-key", "rot-key", category="rotation")
        vault.seed("backblaze-b2-region", "us-west-004")

    @patch.object(state, "verify_leaf_via_rclone", return_value=(True, "PutObject succeeded"), autospec=True)
    @patch("cloud_credentials.leaf_keys.b2.B2Api", autospec=True)
    def test_mints_a_write_only_key_on_the_copy_bucket_and_writes_the_copy_env(self, mock_api_cls, mock_verify, b2_api, vault, fake_vault):
        api = mock_api_cls.return_value = b2_api
        api.get_bucket_by_name.return_value = bucket(api)
        api.create_key.return_value = full_application_key("KEY_ID", "APP_KEY")

        assert state.mint_b2()

        assert api.get_bucket_by_name.call_args.args[0] == state.STATE_BUCKET_B2
        create = api.create_key.call_args.kwargs
        assert create["capabilities"] == state.B2_LEAF_CAPABILITIES["write"]
        assert "deleteFiles" not in create["capabilities"], "the copy key adds objects and can never remove one"
        assert create["valid_duration_seconds"] == state.QUARTERLY_SECONDS
        assert create["key_name"] == state.KEY_NAME_B2
        mock_verify.assert_called_once_with("KEY_ID", "APP_KEY", "https://s3.us-west-004.backblazeb2.com", "us-west-004", state.STATE_BUCKET_B2, "write")
        env = state.read_env_file(copy_env())
        assert env["STATE_COPY_ACCESS_KEY_ID"] == "KEY_ID"
        assert env["STATE_COPY_SECRET_ACCESS_KEY"] == "APP_KEY"
        assert env["STATE_COPY_ENDPOINT"] == "https://s3.us-west-004.backblazeb2.com"
        assert env["STATE_COPY_BUCKET"] == state.STATE_BUCKET_B2
        assert stat.S_IMODE(copy_env().stat().st_mode) == 0o600
        assert vault.get(state.VAULT_NAME_B2_ACCESS) == "KEY_ID"
        assert "APP_KEY" not in fake_vault.store.values(), "only the ID is registered, never the secret"

    @patch.object(state, "verify_leaf_via_rclone", return_value=(False, "PutObject failed: AccessDenied"), autospec=True)
    @patch("cloud_credentials.leaf_keys.b2.B2Api", autospec=True)
    def test_writes_nothing_for_a_key_that_fails_verification(self, mock_api_cls, _verify, b2_api, vault):
        api = mock_api_cls.return_value = b2_api
        api.get_bucket_by_name.return_value = bucket(api)
        api.create_key.return_value = full_application_key("KEY_ID", "APP_KEY")

        assert not state.mint_b2()

        assert not copy_env().exists()
        assert vault.get(state.VAULT_NAME_B2_ACCESS) is None

    @patch.object(state, "verify_leaf_via_rclone", return_value=(True, "PutObject succeeded"), autospec=True)
    @patch("cloud_credentials.leaf_keys.b2.B2Api", autospec=True)
    def test_rotation_writes_the_new_key_before_revoking_the_old_one(self, mock_api_cls, _verify, b2_api, vault):
        api = mock_api_cls.return_value = b2_api
        api.get_bucket_by_name.return_value = bucket(api)
        api.create_key.return_value = full_application_key("NEW_KEY_ID", "NEW_APP_KEY")
        state.write_env_file(copy_env(), {"STATE_COPY_ACCESS_KEY_ID": "OLD_KEY_ID", "STATE_COPY_SECRET_ACCESS_KEY": "old"})
        seen_at_revoke = {}
        registered_at_revoke = []
        api.session.delete_key.side_effect = lambda _id: (
            seen_at_revoke.update(state.read_env_file(copy_env())),
            registered_at_revoke.append(vault.get(state.VAULT_NAME_B2_ACCESS)),
        )

        assert state.mint_b2(rotate=True)

        api.session.delete_key.assert_called_once_with("OLD_KEY_ID")
        assert seen_at_revoke["STATE_COPY_ACCESS_KEY_ID"] == "NEW_KEY_ID"
        assert registered_at_revoke == ["NEW_KEY_ID"], "the freshness check must already see the new ID when the old key goes"

    @patch.object(state, "verify_leaf_via_rclone", return_value=(False, "PutObject failed: AccessDenied"), autospec=True)
    @patch("cloud_credentials.leaf_keys.b2.B2Api", autospec=True)
    def test_rotation_leaves_the_old_key_when_the_new_one_fails_verification(self, mock_api_cls, _verify, b2_api):
        api = mock_api_cls.return_value = b2_api
        api.get_bucket_by_name.return_value = bucket(api)
        api.create_key.return_value = full_application_key("NEW_KEY_ID", "NEW_APP_KEY")
        state.write_env_file(copy_env(), {"STATE_COPY_ACCESS_KEY_ID": "OLD_KEY_ID", "STATE_COPY_SECRET_ACCESS_KEY": "old"})

        assert not state.mint_b2(rotate=True)

        api.session.delete_key.assert_not_called()
        assert state.read_env_file(copy_env())["STATE_COPY_ACCESS_KEY_ID"] == "OLD_KEY_ID"
