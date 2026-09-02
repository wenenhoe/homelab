"""Unit tests for cloud_credentials.leaf_keys.b2.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from _base import RotationTestBase
from cloud_credentials.leaf_keys import b2


def _b2_create_key_response(access_key: str, secret_key: str) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"applicationKeyId": access_key, "applicationKey": secret_key}
    return resp


class B2RotationTests(RotationTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-backblaze-b2-key-id", "rot-id")
        self.seed("_rotation-key-backblaze-b2-application-key", "rot-key")
        self.seed("backblaze-b2-region", "us-west-004")
        self.seed("backblaze-b2-write-access-key", "OLD_ACCESS")
        self.seed("backblaze-b2-write-secret-key", "OLD_SECRET")

    @patch.object(b2, "verify_leaf_via_rclone", return_value=(True, "ok"))
    @patch.object(b2.requests, "Session")
    def test_successful_rotation_revokes_old_key_and_caches_new_one(self, mock_session_cls, mock_verify):
        session = mock_session_cls.return_value
        # b2_authorize uses requests.get directly, not session — patch separately below.
        with patch.object(b2.requests, "get") as mock_get:
            mock_get.return_value = MagicMock(
                raise_for_status=lambda: None,
                json=lambda: {"accountId": "acct", "apiUrl": "https://api", "authorizationToken": "tok"},
            )
            session.post.side_effect = [
                MagicMock(raise_for_status=lambda: None, json=lambda: {"buckets": [{"bucketId": "bkt"}]}),  # bucket lookup
                _b2_create_key_response("NEW_ACCESS", "NEW_SECRET"),  # new key
                MagicMock(raise_for_status=lambda: None),  # delete old key
            ]
            ok = b2.rotate_b2(["write"])

        self.assertTrue(ok)
        # Region matters, not just endpoint: a missing/wrong region is
        # exactly the live bug this caught (OCI 403 SignatureDoesNotMatch
        # outside the tenancy's home region) — assert the actual call
        # arguments, not just that verify ran.
        mock_verify.assert_called_once_with("NEW_ACCESS", "NEW_SECRET", "https://s3.us-west-004.backblazeb2.com", "us-west-004", b2.B2_BUCKET, "write")
        # The old key's delete call must happen, and only after verify passed.
        delete_call = session.post.call_args_list[2]
        self.assertIn("b2_delete_key", delete_call.args[0])
        self.assertEqual(delete_call.kwargs["json"]["applicationKeyId"], "OLD_ACCESS")
        self.assertEqual((self.tmp / "backblaze-b2-write-access-key").read_text(), "NEW_ACCESS")
        self.assertEqual((self.tmp / "backblaze-b2-write-secret-key").read_text(), "NEW_SECRET")

    @patch.object(b2, "verify_leaf_via_rclone", return_value=(False, "auth failed"))
    @patch.object(b2.requests, "Session")
    def test_failed_verification_leaves_old_key_untouched(self, mock_session_cls, mock_verify):
        session = mock_session_cls.return_value
        with patch.object(b2.requests, "get") as mock_get:
            mock_get.return_value = MagicMock(
                raise_for_status=lambda: None,
                json=lambda: {"accountId": "acct", "apiUrl": "https://api", "authorizationToken": "tok"},
            )
            session.post.side_effect = [
                MagicMock(raise_for_status=lambda: None, json=lambda: {"buckets": [{"bucketId": "bkt"}]}),  # bucket lookup
                _b2_create_key_response("NEW_ACCESS", "NEW_SECRET"),  # new key created
            ]
            ok = b2.rotate_b2(["write"])

        self.assertFalse(ok)
        # No delete call: only 2 session.post calls happened (bucket lookup + create).
        self.assertEqual(session.post.call_count, 2)
        # Cache must be untouched — the old, still-valid key stays authoritative.
        self.assertEqual((self.tmp / "backblaze-b2-write-access-key").read_text(), "OLD_ACCESS")
        self.assertEqual((self.tmp / "backblaze-b2-write-secret-key").read_text(), "OLD_SECRET")


if __name__ == "__main__":
    import unittest

    unittest.main()
