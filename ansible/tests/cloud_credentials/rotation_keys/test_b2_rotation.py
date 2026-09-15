"""Unit tests for cloud_credentials.rotation_keys.b2.

Run via `uv run pytest ansible/tests/ -v`. Every B2 call is mocked at
the b2sdk B2Api boundary (Stage 3); nothing here talks to a real
account.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _fake_vault import FakeVaultTestCase
from b2sdk.v2 import FullApplicationKey
from cloud_credentials.rotation_keys import b2 as rotation_b2


class B2RotationKeyTestBase(FakeVaultTestCase):
    def seed(self, name: str, value: str) -> None:
        self.vault_seed("rotation", name, value)

    def get(self, name: str) -> str | None:
        return self.vault_get("rotation", name)


class CreateB2RotationKeyTests(B2RotationKeyTestBase):
    @patch.object(rotation_b2, "_prompt_master_credentials", return_value=("masterKeyId", "masterKey"))
    @patch.object(rotation_b2, "_mint_rotation_key")
    def test_mints_and_caches_on_first_run(self, mock_mint, mock_prompt):
        mock_mint.return_value = {"master_api": MagicMock(), "key_id": "NEW_ID", "app_key": "NEW_KEY"}

        rotation_b2.create_b2_rotation_key()

        self.assertEqual(self.get("_rotation-key-backblaze-b2-key-id"), "NEW_ID")
        self.assertEqual(self.get("_rotation-key-backblaze-b2-application-key"), "NEW_KEY")

    @patch.object(rotation_b2, "_prompt_master_credentials")
    def test_skips_entirely_when_already_cached(self, mock_prompt):
        self.seed("_rotation-key-backblaze-b2-key-id", "EXISTING_ID")
        self.seed("_rotation-key-backblaze-b2-application-key", "EXISTING_KEY")

        rotation_b2.create_b2_rotation_key()

        # The whole point of the cache check: never re-prompt for master
        # credentials once a rotation key already exists.
        mock_prompt.assert_not_called()


class MintRotationKeyTests(FakeVaultTestCase):
    @patch.object(rotation_b2, "B2Api")
    def test_mints_with_account_wide_key_management_capabilities_only(self, mock_api_cls):
        """The point of docs/cloud-credential-creation.md's B2 section:
        no bucket_id (rejected outright by B2 for these capabilities),
        and file/bucket-data capabilities excluded entirely - this key
        can only manage other keys."""
        api = mock_api_cls.return_value
        api.create_key.return_value = MagicMock(spec=FullApplicationKey, id_="NEW_ID", application_key="NEW_KEY")

        minted = rotation_b2._mint_rotation_key("masterKeyId", "masterKey")

        api.authorize_account.assert_called_once_with("production", "masterKeyId", "masterKey")
        sent = api.create_key.call_args.kwargs
        self.assertEqual(set(sent["capabilities"]), {"listKeys", "writeKeys", "deleteKeys", "listBuckets"})
        self.assertNotIn("bucket_id", sent)
        self.assertEqual(minted["key_id"], "NEW_ID")
        self.assertEqual(minted["app_key"], "NEW_KEY")


class RotateB2RotationKeyTests(B2RotationKeyTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-backblaze-b2-key-id", "OLD_ID")
        self.seed("_rotation-key-backblaze-b2-application-key", "OLD_KEY")

    @patch.object(rotation_b2, "_prompt_master_credentials", return_value=("masterKeyId", "masterKey"))
    @patch.object(rotation_b2, "_mint_rotation_key")
    @patch.object(rotation_b2, "_verify_rotation_key", return_value=(True, ""))
    def test_successful_rotation_revokes_old_key_and_caches_new(self, mock_verify, mock_mint, mock_prompt):
        master_api = MagicMock()
        mock_mint.return_value = {"master_api": master_api, "key_id": "NEW_ID", "app_key": "NEW_KEY"}

        ok = rotation_b2.rotate_b2_rotation_key()

        self.assertTrue(ok)
        mock_verify.assert_called_once_with("NEW_ID", "NEW_KEY")
        # Revoked via the master session that minted the new key, not
        # the (about-to-be-invalid) old rotation key itself.
        master_api.session.delete_key.assert_called_once_with("OLD_ID")
        self.assertEqual(self.get("_rotation-key-backblaze-b2-key-id"), "NEW_ID")
        self.assertEqual(self.get("_rotation-key-backblaze-b2-application-key"), "NEW_KEY")

    @patch.object(rotation_b2, "_prompt_master_credentials", return_value=("masterKeyId", "masterKey"))
    @patch.object(rotation_b2, "_mint_rotation_key")
    @patch.object(rotation_b2, "_verify_rotation_key", return_value=(False, "401 unauthorized"))
    def test_failed_verification_leaves_old_key_cached_and_unrevoked(self, mock_verify, mock_mint, mock_prompt):
        master_api = MagicMock()
        mock_mint.return_value = {"master_api": master_api, "key_id": "NEW_ID", "app_key": "NEW_KEY"}

        ok = rotation_b2.rotate_b2_rotation_key()

        self.assertFalse(ok)
        # The old, still-working rotation key must survive a failed
        # rotation untouched — no revoke call at all.
        master_api.session.delete_key.assert_not_called()
        self.assertEqual(self.get("_rotation-key-backblaze-b2-key-id"), "OLD_ID")

    @patch.object(rotation_b2, "_prompt_master_credentials", return_value=("masterKeyId", "masterKey"))
    @patch.object(rotation_b2, "_mint_rotation_key")
    @patch.object(rotation_b2, "_verify_rotation_key", return_value=(True, ""))
    def test_rotate_always_re_prompts_for_master_credentials(self, mock_verify, mock_mint, mock_prompt):
        # B2 has no way to mint an account-management key from another
        # account-management key — only the master credential can, same
        # requirement as create_b2_rotation_key's first run.
        mock_mint.return_value = {"master_api": MagicMock(), "key_id": "NEW_ID", "app_key": "NEW_KEY"}

        rotation_b2.rotate_b2_rotation_key()

        mock_prompt.assert_called_once()


if __name__ == "__main__":
    import unittest

    unittest.main()
