"""Unit tests for cloud_credentials.create_snapshot_readonly_keys.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "leaf_keys"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from _base import RotationTestBase
from cloud_credentials import create_snapshot_readonly_keys as snap


class MintR2Tests(RotationTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-cloudflare-r2-token", "admin-token")
        self.seed("cloudflare-r2-account-id", "acct123")

    @patch.object(snap, "r2_permission_group_ids", return_value={"Workers R2 Storage Bucket Item Read": "grp-read"})
    @patch.object(snap.requests, "Session")
    def test_mints_readonly_token_scoped_to_the_snapshot_bucket_with_no_expiry(self, mock_session_cls, _mock_groups):
        session = mock_session_cls.return_value
        session.post.return_value = MagicMock(json=lambda: {"success": True, "result": {"id": "TOKEN_ID", "value": "token-value"}})

        snap.mint_r2()

        create_call = session.post.call_args
        body = create_call.kwargs["json"]
        self.assertIn(f"acct123_default_{snap.SNAPSHOT_BUCKET_R2}", next(iter(body["policies"][0]["resources"])))
        self.assertNotIn("expires_on", body, "the break-glass snapshot credential must not carry the quarterly leaf expiry")
        self.assertEqual(body["name"], "openbao-snapshot-readonly")

    def test_fails_loudly_without_the_r2_admin_token_cached(self):
        # setUp seeded the token; a fresh instance without it must not
        # silently prompt or proceed — require_cache_file's own exit(1)
        # is exercised via r2_rotation_token's underlying getpass path,
        # covered by test_r2.py already. This asserts the account-id
        # guard specifically, since mint_r2 needs both.
        from cloud_credentials.cache import SECRETS_DIR

        (SECRETS_DIR / "cloudflare-r2-account-id").unlink()
        with self.assertRaises(SystemExit):
            snap.mint_r2()


class MintB2Tests(RotationTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-backblaze-b2-key-id", "rot-id")
        self.seed("_rotation-key-backblaze-b2-application-key", "rot-key")

    @patch.object(snap.requests, "get")
    def test_mints_readonly_key_scoped_to_the_snapshot_bucket_with_no_expiry(self, mock_get):
        mock_get.return_value = MagicMock(
            raise_for_status=lambda: None,
            json=lambda: {"accountId": "acct", "apiUrl": "https://api", "authorizationToken": "tok"},
        )
        with patch("cloud_credentials.leaf_keys.b2.requests.Session") as mock_session_cls:
            session = mock_session_cls.return_value
            session.post.side_effect = [
                MagicMock(raise_for_status=lambda: None, json=lambda: {"buckets": [{"bucketId": "bkt"}]}),  # bucket lookup
                MagicMock(raise_for_status=lambda: None, json=lambda: {"applicationKeyId": "KEY_ID", "applicationKey": "APP_KEY"}),
            ]
            snap.mint_b2()

        bucket_lookup_call = session.post.call_args_list[0]
        self.assertEqual(bucket_lookup_call.kwargs["json"]["bucketName"], snap.SNAPSHOT_BUCKET_B2)

        create_call = session.post.call_args_list[1]
        body = create_call.kwargs["json"]
        self.assertEqual(body["capabilities"], snap.B2_LEAF_CAPABILITIES["read"])
        self.assertNotIn("validDurationInSeconds", body, "the break-glass snapshot credential must not carry the quarterly leaf expiry")
        self.assertEqual(body["keyName"], "openbao-snapshot-readonly")
