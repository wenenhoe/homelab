"""Unit tests for cloud_credentials.leaf_keys.r2.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from _base import RotationTestBase
from cloud_credentials.leaf_keys import r2


class R2RotationTokenTests(RotationTestBase):
    """Covers caching the R2 admin token — the actual change requested:
    stop re-prompting for a value that was always the same human-created
    Console token."""

    def test_prompts_and_caches_when_nothing_cached(self):
        with patch.object(r2.getpass, "getpass", return_value="cf-token-value") as mock_prompt:
            token = r2.r2_rotation_token()
        mock_prompt.assert_called_once()
        self.assertEqual(token, "cf-token-value")
        self.assertEqual((self.tmp / "_rotation-key-cloudflare-r2-token").read_text(), "cf-token-value")

    def test_uses_cache_without_prompting_on_subsequent_calls(self):
        self.seed("_rotation-key-cloudflare-r2-token", "cached-token-value")
        with patch.object(r2.getpass, "getpass") as mock_prompt:
            token = r2.r2_rotation_token()
        mock_prompt.assert_not_called()
        self.assertEqual(token, "cached-token-value")


class R2RotationTests(RotationTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-cloudflare-r2-token", "admin-token")
        self.seed("cloudflare-r2-account-id", "acct123")
        self.seed("cloudflare-r2-write-access-key", "OLD_TOKEN_ID")
        self.seed("cloudflare-r2-write-secret-key", "old_secret_hash")

    def _permission_groups_response(self):
        return MagicMock(
            json=lambda: {
                "success": True,
                "result": [
                    {"name": "Workers R2 Storage Bucket Item Write", "id": "grp-write"},
                    {"name": "Workers R2 Storage Bucket Item Read", "id": "grp-read"},
                ],
            }
        )

    def _create_token_response(self, token_id, token_value):
        return MagicMock(json=lambda: {"success": True, "result": {"id": token_id, "value": token_value}})

    @patch.object(r2, "verify_leaf_via_rclone", return_value=(True, "ok"))
    @patch.object(r2.requests, "Session")
    def test_successful_rotation_deletes_old_token_and_caches_new_one(self, mock_session_cls, mock_verify):
        session = mock_session_cls.return_value
        session.get.return_value = self._permission_groups_response()
        session.post.return_value = self._create_token_response("NEW_TOKEN_ID", "new-token-value")
        session.delete.return_value = MagicMock(json=lambda: {"success": True})

        ok = r2.rotate_r2(["write"])

        self.assertTrue(ok)
        mock_verify.assert_called_once_with(
            "NEW_TOKEN_ID",
            hashlib.sha256(b"new-token-value").hexdigest(),
            "https://acct123.r2.cloudflarestorage.com",
            "auto",
            r2.R2_BUCKET,
            "write",
        )
        session.delete.assert_called_once()
        self.assertIn("OLD_TOKEN_ID", session.delete.call_args.args[0])
        self.assertEqual((self.tmp / "cloudflare-r2-write-access-key").read_text(), "NEW_TOKEN_ID")

    @patch.object(r2, "verify_leaf_via_rclone", return_value=(False, "denied"))
    @patch.object(r2.requests, "Session")
    def test_failed_verification_leaves_old_token_untouched(self, mock_session_cls, mock_verify):
        session = mock_session_cls.return_value
        session.get.return_value = self._permission_groups_response()
        session.post.return_value = self._create_token_response("NEW_TOKEN_ID", "new-token-value")

        ok = r2.rotate_r2(["write"])

        self.assertFalse(ok)
        session.delete.assert_not_called()
        self.assertEqual((self.tmp / "cloudflare-r2-write-access-key").read_text(), "OLD_TOKEN_ID")


if __name__ == "__main__":
    import unittest

    unittest.main()
