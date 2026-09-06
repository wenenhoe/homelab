"""Unit tests for cloud_credentials.create_snapshot_write_keys.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "leaf_keys"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from _base import RotationTestBase
from cloud_credentials import create_snapshot_write_keys as snap


class MintR2Tests(RotationTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-cloudflare-r2-token", "admin-token")
        self.seed("cloudflare-r2-account-id", "acct123")

    @patch.object(snap, "verify_leaf_via_rclone", return_value=(True, "PutObject succeeded"))
    @patch.object(snap, "r2_permission_group_ids", return_value={"Workers R2 Storage Bucket Item Write": "grp-write"})
    @patch.object(snap.requests, "Session")
    def test_mints_write_leaf_scoped_to_the_snapshot_bucket_with_quarterly_expiry(self, mock_session_cls, _mock_groups, mock_verify):
        session = mock_session_cls.return_value
        session.post.return_value = MagicMock(json=lambda: {"success": True, "result": {"id": "TOKEN_ID", "value": "token-value"}})

        ok = snap.mint_r2()

        self.assertTrue(ok)
        create_call = session.post.call_args
        body = create_call.kwargs["json"]
        self.assertIn(f"acct123_default_{snap.SNAPSHOT_BUCKET_R2}", next(iter(body["policies"][0]["resources"])))
        self.assertIn("expires_on", body, "unlike the break-glass read-only credential, this one IS on the quarterly rotation cycle")
        self.assertEqual(body["name"], snap.TOKEN_NAME_R2)
        mock_verify.assert_called_once_with(
            "TOKEN_ID",
            snap.hashlib.sha256(b"token-value").hexdigest(),
            "https://acct123.r2.cloudflarestorage.com",
            "auto",
            snap.SNAPSHOT_BUCKET_R2,
            "write",
        )
        self.assertEqual(snap.read_cache(snap.CACHE_R2_ACCESS), "TOKEN_ID")

    @patch.object(snap, "verify_leaf_via_rclone", return_value=(False, "rclone lsjson (PutObject) failed: AccessDenied"))
    @patch.object(snap, "r2_permission_group_ids", return_value={"Workers R2 Storage Bucket Item Write": "grp-write"})
    @patch.object(snap.requests, "Session")
    def test_does_not_cache_a_credential_that_fails_verification(self, mock_session_cls, _mock_groups, _mock_verify):
        session = mock_session_cls.return_value
        session.post.return_value = MagicMock(json=lambda: {"success": True, "result": {"id": "TOKEN_ID", "value": "token-value"}})

        ok = snap.mint_r2()

        self.assertFalse(ok)
        self.assertIsNone(snap.read_cache(snap.CACHE_R2_ACCESS), "a credential that fails its own rclone check must never be cached")

    def test_skips_if_already_cached(self):
        self.seed(snap.CACHE_R2_ACCESS, "existing-id")
        self.seed(snap.CACHE_R2_SECRET, "existing-secret")

        ok = snap.mint_r2()

        self.assertTrue(ok)


class MintB2Tests(RotationTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-backblaze-b2-key-id", "rot-id")
        self.seed("_rotation-key-backblaze-b2-application-key", "rot-key")
        self.seed("backblaze-b2-region", "us-west-004")

    @patch.object(snap, "verify_leaf_via_rclone", return_value=(True, "PutObject succeeded"))
    @patch.object(snap.requests, "get")
    def test_mints_write_key_scoped_to_the_snapshot_bucket_with_quarterly_expiry(self, mock_get, mock_verify):
        mock_get.return_value = MagicMock(
            raise_for_status=lambda: None,
            json=lambda: {"accountId": "acct", "apiUrl": "https://api", "authorizationToken": "tok"},
        )
        with patch("cloud_credentials.leaf_keys.b2.requests.Session") as mock_session_cls:
            session = mock_session_cls.return_value
            session.post.side_effect = [
                MagicMock(raise_for_status=lambda: None, json=lambda: {"buckets": [{"bucketId": "bkt"}]}),
                MagicMock(raise_for_status=lambda: None, json=lambda: {"applicationKeyId": "KEY_ID", "applicationKey": "APP_KEY"}),
            ]
            ok = snap.mint_b2()

        self.assertTrue(ok)
        bucket_lookup_call = session.post.call_args_list[0]
        self.assertEqual(bucket_lookup_call.kwargs["json"]["bucketName"], snap.SNAPSHOT_BUCKET_B2)

        create_call = session.post.call_args_list[1]
        body = create_call.kwargs["json"]
        self.assertEqual(body["capabilities"], snap.B2_LEAF_CAPABILITIES["write"])
        self.assertNotIn("deleteFiles", body["capabilities"])
        self.assertEqual(body["validDurationInSeconds"], snap.QUARTERLY_SECONDS)
        self.assertEqual(body["keyName"], snap.KEY_NAME_B2)
        mock_verify.assert_called_once_with(
            "KEY_ID",
            "APP_KEY",
            "https://s3.us-west-004.backblazeb2.com",
            "us-west-004",
            snap.SNAPSHOT_BUCKET_B2,
            "write",
        )
        self.assertEqual(snap.read_cache(snap.CACHE_B2_ACCESS), "KEY_ID")

    @patch.object(snap, "verify_leaf_via_rclone", return_value=(False, "rclone lsjson (PutObject) failed: AccessDenied"))
    @patch.object(snap.requests, "get")
    def test_does_not_cache_a_credential_that_fails_verification(self, mock_get, _mock_verify):
        mock_get.return_value = MagicMock(
            raise_for_status=lambda: None,
            json=lambda: {"accountId": "acct", "apiUrl": "https://api", "authorizationToken": "tok"},
        )
        with patch("cloud_credentials.leaf_keys.b2.requests.Session") as mock_session_cls:
            session = mock_session_cls.return_value
            session.post.side_effect = [
                MagicMock(raise_for_status=lambda: None, json=lambda: {"buckets": [{"bucketId": "bkt"}]}),
                MagicMock(raise_for_status=lambda: None, json=lambda: {"applicationKeyId": "KEY_ID", "applicationKey": "APP_KEY"}),
            ]
            ok = snap.mint_b2()

        self.assertFalse(ok)
        self.assertIsNone(snap.read_cache(snap.CACHE_B2_ACCESS))

    def test_skips_if_already_cached(self):
        self.seed(snap.CACHE_B2_ACCESS, "existing-id")
        self.seed(snap.CACHE_B2_SECRET, "existing-secret")

        ok = snap.mint_b2()

        self.assertTrue(ok)


class RotateR2Tests(RotationTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-cloudflare-r2-token", "admin-token")
        self.seed("cloudflare-r2-account-id", "acct123")
        self.seed(snap.CACHE_R2_ACCESS, "OLD_TOKEN_ID")
        self.seed(snap.CACHE_R2_SECRET, "old-secret")

    @patch.object(snap, "r2_delete_token")
    @patch.object(snap, "verify_leaf_via_rclone", return_value=(True, "PutObject succeeded"))
    @patch.object(snap, "r2_permission_group_ids", return_value={"Workers R2 Storage Bucket Item Write": "grp-write"})
    @patch.object(snap.requests, "Session")
    def test_verifies_new_token_before_revoking_the_old_one(self, mock_session_cls, _mock_groups, _mock_verify, mock_delete):
        session = mock_session_cls.return_value
        session.post.return_value = MagicMock(json=lambda: {"success": True, "result": {"id": "NEW_TOKEN_ID", "value": "new-value"}})

        ok = snap.rotate_r2()

        self.assertTrue(ok)
        mock_delete.assert_called_once_with(session, "acct123", "OLD_TOKEN_ID")
        self.assertEqual(snap.read_cache(snap.CACHE_R2_ACCESS), "NEW_TOKEN_ID")

    @patch.object(snap, "r2_delete_token")
    @patch.object(snap, "verify_leaf_via_rclone", return_value=(False, "PutObject failed: AccessDenied"))
    @patch.object(snap, "r2_permission_group_ids", return_value={"Workers R2 Storage Bucket Item Write": "grp-write"})
    @patch.object(snap.requests, "Session")
    def test_leaves_old_token_untouched_when_new_one_fails_verification(self, mock_session_cls, _mock_groups, _mock_verify, mock_delete):
        session = mock_session_cls.return_value
        session.post.return_value = MagicMock(json=lambda: {"success": True, "result": {"id": "NEW_TOKEN_ID", "value": "new-value"}})

        ok = snap.rotate_r2()

        self.assertFalse(ok)
        mock_delete.assert_not_called()
        self.assertEqual(snap.read_cache(snap.CACHE_R2_ACCESS), "OLD_TOKEN_ID", "old credential must stay live and cached until a new one actually verifies")
