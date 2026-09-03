"""Unit tests for cloud_credentials.rotation_keys.b2.

Run via `uv run pytest ansible/tests/ -v`. Every B2 HTTP call is
mocked; nothing here talks to a real account.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from cloud_credentials import cache
from cloud_credentials.rotation_keys import b2 as rotation_b2


class B2RotationKeyTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(cache, "SECRETS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)


class CreateB2RotationKeyTests(B2RotationKeyTestBase):
    @patch.object(rotation_b2, "_prompt_master_credentials", return_value=("masterKeyId", "masterKey"))
    @patch.object(rotation_b2, "_mint_rotation_key")
    def test_mints_and_caches_on_first_run(self, mock_mint, mock_prompt):
        mock_mint.return_value = {"master_session": MagicMock(), "api_url": "https://api", "key_id": "NEW_ID", "app_key": "NEW_KEY"}

        rotation_b2.create_b2_rotation_key()

        self.assertEqual((self.tmp / "_rotation-key-backblaze-b2-key-id").read_text(), "NEW_ID")
        self.assertEqual((self.tmp / "_rotation-key-backblaze-b2-application-key").read_text(), "NEW_KEY")

    @patch.object(rotation_b2, "_prompt_master_credentials")
    def test_skips_entirely_when_already_cached(self, mock_prompt):
        cache.write_cache("_rotation-key-backblaze-b2-key-id", "EXISTING_ID")
        cache.write_cache("_rotation-key-backblaze-b2-application-key", "EXISTING_KEY")

        rotation_b2.create_b2_rotation_key()

        # The whole point of the cache check: never re-prompt for master
        # credentials once a rotation key already exists.
        mock_prompt.assert_not_called()


class RotateB2RotationKeyTests(B2RotationKeyTestBase):
    def setUp(self):
        super().setUp()
        cache.write_cache("_rotation-key-backblaze-b2-key-id", "OLD_ID")
        cache.write_cache("_rotation-key-backblaze-b2-application-key", "OLD_KEY")

    @patch.object(rotation_b2, "_prompt_master_credentials", return_value=("masterKeyId", "masterKey"))
    @patch.object(rotation_b2, "_mint_rotation_key")
    @patch.object(rotation_b2, "_verify_rotation_key", return_value=(True, ""))
    def test_successful_rotation_revokes_old_key_and_caches_new(self, mock_verify, mock_mint, mock_prompt):
        master_session = MagicMock()
        mock_mint.return_value = {"master_session": master_session, "api_url": "https://api", "key_id": "NEW_ID", "app_key": "NEW_KEY"}

        ok = rotation_b2.rotate_b2_rotation_key()

        self.assertTrue(ok)
        mock_verify.assert_called_once_with("NEW_ID", "NEW_KEY")
        # Revoked via the master session that minted the new key, not
        # the (about-to-be-invalid) old rotation key itself.
        master_session.post.assert_called_once()
        self.assertIn("b2_delete_key", master_session.post.call_args.args[0])
        self.assertEqual(master_session.post.call_args.kwargs["json"]["applicationKeyId"], "OLD_ID")
        self.assertEqual((self.tmp / "_rotation-key-backblaze-b2-key-id").read_text(), "NEW_ID")
        self.assertEqual((self.tmp / "_rotation-key-backblaze-b2-application-key").read_text(), "NEW_KEY")

    @patch.object(rotation_b2, "_prompt_master_credentials", return_value=("masterKeyId", "masterKey"))
    @patch.object(rotation_b2, "_mint_rotation_key")
    @patch.object(rotation_b2, "_verify_rotation_key", return_value=(False, "401 unauthorized"))
    def test_failed_verification_leaves_old_key_cached_and_unrevoked(self, mock_verify, mock_mint, mock_prompt):
        master_session = MagicMock()
        mock_mint.return_value = {"master_session": master_session, "api_url": "https://api", "key_id": "NEW_ID", "app_key": "NEW_KEY"}

        ok = rotation_b2.rotate_b2_rotation_key()

        self.assertFalse(ok)
        # The old, still-working rotation key must survive a failed
        # rotation untouched — no revoke call at all.
        master_session.post.assert_not_called()
        self.assertEqual((self.tmp / "_rotation-key-backblaze-b2-key-id").read_text(), "OLD_ID")

    @patch.object(rotation_b2, "_prompt_master_credentials", return_value=("masterKeyId", "masterKey"))
    @patch.object(rotation_b2, "_mint_rotation_key")
    @patch.object(rotation_b2, "_verify_rotation_key", return_value=(True, ""))
    def test_rotate_always_re_prompts_for_master_credentials(self, mock_verify, mock_mint, mock_prompt):
        # B2 has no way to mint an account-management key from another
        # account-management key — only the master credential can, same
        # requirement as create_b2_rotation_key's first run.
        mock_mint.return_value = {"master_session": MagicMock(), "api_url": "https://api", "key_id": "NEW_ID", "app_key": "NEW_KEY"}

        rotation_b2.rotate_b2_rotation_key()

        mock_prompt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
