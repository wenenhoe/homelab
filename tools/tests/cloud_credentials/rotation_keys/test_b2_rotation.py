"""Unit tests for cloud_credentials.rotation_keys.b2.

Run via `uv run pytest tools/tests/ -v`. Every B2 call is mocked at
the b2sdk B2Api boundary (Stage 3); nothing here talks to a real
account.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from _b2_objects import full_application_key, stubbed_b2_api
from cloud_credentials.rotation_keys import b2 as rotation_b2


class TestCreateB2RotationKey:
    @patch.object(rotation_b2, "_prompt_master_credentials", return_value=("masterKeyId", "masterKey"))
    @patch.object(rotation_b2, "_mint_rotation_key")
    def test_mints_and_caches_on_first_run(self, mock_mint, mock_prompt, rotation_vault):
        mock_mint.return_value = {"master_api": stubbed_b2_api(), "key_id": "NEW_ID", "app_key": "NEW_KEY"}

        rotation_b2.create_b2_rotation_key()

        assert rotation_vault.get("_rotation-key-backblaze-b2-key-id") == "NEW_ID"
        assert rotation_vault.get("_rotation-key-backblaze-b2-application-key") == "NEW_KEY"

    @patch.object(rotation_b2, "_prompt_master_credentials")
    def test_skips_entirely_when_already_cached(self, mock_prompt, rotation_vault):
        rotation_vault.seed("_rotation-key-backblaze-b2-key-id", "EXISTING_ID")
        rotation_vault.seed("_rotation-key-backblaze-b2-application-key", "EXISTING_KEY")

        rotation_b2.create_b2_rotation_key()

        # The whole point of the cache check: never re-prompt for master
        # credentials once a rotation key already exists.
        mock_prompt.assert_not_called()
        assert rotation_vault.get("_rotation-key-backblaze-b2-key-id") == "EXISTING_ID"
        assert rotation_vault.get("_rotation-key-backblaze-b2-application-key") == "EXISTING_KEY"


@pytest.mark.usefixtures("fake_vault")
class TestMintRotationKey:
    @patch.object(rotation_b2, "B2Api", autospec=True)
    def test_mints_with_account_wide_key_management_capabilities_only(self, mock_api_cls, b2_api):
        """The point of docs/topics/secrets/cloud-credentials/scoping.md's B2 section:
        no bucket_id (rejected outright by B2 for these capabilities),
        and file/bucket-data capabilities excluded entirely - this key
        can only manage other keys."""
        api = mock_api_cls.return_value = b2_api
        api.create_key.return_value = full_application_key("NEW_ID", "NEW_KEY")

        minted = rotation_b2._mint_rotation_key("masterKeyId", "masterKey")

        api.authorize_account.assert_called_once_with("production", "masterKeyId", "masterKey")
        sent = api.create_key.call_args.kwargs
        assert set(sent["capabilities"]) == {"listKeys", "writeKeys", "deleteKeys", "listBuckets"}
        assert "bucket_id" not in sent
        assert minted["key_id"] == "NEW_ID"
        assert minted["app_key"] == "NEW_KEY"


class TestRotateB2RotationKey:
    @pytest.fixture(autouse=True)
    def _seeded(self, rotation_vault):
        rotation_vault.seed("_rotation-key-backblaze-b2-key-id", "OLD_ID")
        rotation_vault.seed("_rotation-key-backblaze-b2-application-key", "OLD_KEY")

    @patch.object(rotation_b2, "_prompt_master_credentials", return_value=("masterKeyId", "masterKey"))
    @patch.object(rotation_b2, "_mint_rotation_key")
    @patch.object(rotation_b2, "_verify_rotation_key", return_value=(True, ""))
    def test_successful_rotation_revokes_old_key_and_caches_new(self, mock_verify, mock_mint, mock_prompt, rotation_vault):
        master_api = stubbed_b2_api()
        mock_mint.return_value = {"master_api": master_api, "key_id": "NEW_ID", "app_key": "NEW_KEY"}

        ok = rotation_b2.rotate_b2_rotation_key()

        assert ok
        mock_verify.assert_called_once_with("NEW_ID", "NEW_KEY")
        # Revoked via the master session that minted the new key, not
        # the (about-to-be-invalid) old rotation key itself.
        master_api.session.delete_key.assert_called_once_with("OLD_ID")
        assert rotation_vault.get("_rotation-key-backblaze-b2-key-id") == "NEW_ID"
        assert rotation_vault.get("_rotation-key-backblaze-b2-application-key") == "NEW_KEY"

    @patch.object(rotation_b2, "_prompt_master_credentials", return_value=("masterKeyId", "masterKey"))
    @patch.object(rotation_b2, "_mint_rotation_key")
    @patch.object(rotation_b2, "_verify_rotation_key", return_value=(False, "401 unauthorized"))
    def test_failed_verification_leaves_old_key_cached_and_unrevoked(self, mock_verify, mock_mint, mock_prompt, rotation_vault):
        master_api = stubbed_b2_api()
        mock_mint.return_value = {"master_api": master_api, "key_id": "NEW_ID", "app_key": "NEW_KEY"}

        ok = rotation_b2.rotate_b2_rotation_key()

        assert not ok
        # The old, still-working rotation key must survive a failed
        # rotation untouched — no revoke call at all.
        master_api.session.delete_key.assert_not_called()
        assert rotation_vault.get("_rotation-key-backblaze-b2-key-id") == "OLD_ID"

    @patch.object(rotation_b2, "_prompt_master_credentials", return_value=("masterKeyId", "masterKey"))
    @patch.object(rotation_b2, "_mint_rotation_key")
    @patch.object(rotation_b2, "_verify_rotation_key", return_value=(True, ""))
    def test_rotate_always_re_prompts_for_master_credentials(self, mock_verify, mock_mint, mock_prompt):
        # B2 has no way to mint an account-management key from another
        # account-management key — only the master credential can, same
        # requirement as create_b2_rotation_key's first run.
        mock_mint.return_value = {"master_api": stubbed_b2_api(), "key_id": "NEW_ID", "app_key": "NEW_KEY"}

        rotation_b2.rotate_b2_rotation_key()

        mock_prompt.assert_called_once()
        mock_mint.assert_called_once_with("masterKeyId", "masterKey")
