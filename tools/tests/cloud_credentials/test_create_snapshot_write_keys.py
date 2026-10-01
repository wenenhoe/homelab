"""Unit tests for cloud_credentials.create_snapshot_write_keys.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from _responses import response
from b2sdk.v2 import FullApplicationKey
from cloud_credentials import create_snapshot_write_keys as snap


class TestMintR2:
    @pytest.fixture(autouse=True)
    def _seeded(self, vault):
        vault.seed("_rotation-key-cloudflare-r2-token", "admin-token", category="rotation")
        vault.seed("cloudflare-r2-account-id", "acct123")

    @patch.object(snap, "verify_leaf_via_rclone", return_value=(True, "PutObject succeeded"))
    @patch.object(snap, "r2_permission_group_ids", return_value={"Workers R2 Storage Bucket Item Write": "grp-write"})
    def test_mints_write_leaf_scoped_to_the_snapshot_bucket_with_quarterly_expiry(self, _mock_groups, mock_verify, session_class):
        session = session_class.return_value
        session.post.return_value = response(json_body={"success": True, "result": {"id": "TOKEN_ID", "value": "token-value"}})

        ok = snap.mint_r2()

        assert ok
        create_call = session.post.call_args
        body = create_call.kwargs["json"]
        assert f"acct123_default_{snap.SNAPSHOT_BUCKET_R2}" in next(iter(body["policies"][0]["resources"]))
        assert "expires_on" in body, "unlike the break-glass read-only credential, this one IS on the quarterly rotation cycle"
        assert body["name"] == snap.TOKEN_NAME_R2
        mock_verify.assert_called_once_with(
            "TOKEN_ID",
            snap.hashlib.sha256(b"token-value").hexdigest(),
            "https://acct123.r2.cloudflarestorage.com",
            "auto",
            snap.SNAPSHOT_BUCKET_R2,
            "write",
        )
        assert snap.read_cache(snap.CACHE_R2_ACCESS) == "TOKEN_ID"

    @patch.object(snap, "verify_leaf_via_rclone", return_value=(False, "rclone lsjson (PutObject) failed: AccessDenied"))
    @patch.object(snap, "r2_permission_group_ids", return_value={"Workers R2 Storage Bucket Item Write": "grp-write"})
    def test_does_not_cache_a_credential_that_fails_verification(self, _mock_groups, _mock_verify, session_class):
        session = session_class.return_value
        session.post.return_value = response(json_body={"success": True, "result": {"id": "TOKEN_ID", "value": "token-value"}})

        ok = snap.mint_r2()

        assert not ok
        assert snap.read_cache(snap.CACHE_R2_ACCESS) is None, "a credential that fails its own rclone check must never be cached"

    def test_skips_if_already_cached(self, vault):
        vault.seed(snap.CACHE_R2_ACCESS, "existing-id")
        vault.seed(snap.CACHE_R2_SECRET, "existing-secret")

        ok = snap.mint_r2()

        assert ok


class TestMintB2:
    @pytest.fixture(autouse=True)
    def _seeded(self, vault):
        vault.seed("_rotation-key-backblaze-b2-key-id", "rot-id", category="rotation")
        vault.seed("_rotation-key-backblaze-b2-application-key", "rot-key", category="rotation")
        vault.seed("backblaze-b2-region", "us-west-004")

    @patch.object(snap, "verify_leaf_via_rclone", return_value=(True, "PutObject succeeded"))
    @patch("cloud_credentials.leaf_keys.b2.B2Api")
    def test_mints_write_key_scoped_to_the_snapshot_bucket_with_quarterly_expiry(self, mock_api_cls, mock_verify):
        api = mock_api_cls.return_value
        api.get_bucket_by_name.return_value = MagicMock(id_="bkt")
        api.create_key.return_value = MagicMock(spec=FullApplicationKey, id_="KEY_ID", application_key="APP_KEY")

        ok = snap.mint_b2()

        assert ok
        bucket_lookup_call = api.get_bucket_by_name.call_args
        assert bucket_lookup_call.args[0] == snap.SNAPSHOT_BUCKET_B2

        create_call = api.create_key.call_args
        assert create_call.kwargs["capabilities"] == snap.B2_LEAF_CAPABILITIES["write"]
        assert "deleteFiles" not in create_call.kwargs["capabilities"]
        assert create_call.kwargs["valid_duration_seconds"] == snap.QUARTERLY_SECONDS
        assert create_call.kwargs["key_name"] == snap.KEY_NAME_B2
        mock_verify.assert_called_once_with(
            "KEY_ID",
            "APP_KEY",
            "https://s3.us-west-004.backblazeb2.com",
            "us-west-004",
            snap.SNAPSHOT_BUCKET_B2,
            "write",
        )
        assert snap.read_cache(snap.CACHE_B2_ACCESS) == "KEY_ID"

    @patch.object(snap, "verify_leaf_via_rclone", return_value=(False, "rclone lsjson (PutObject) failed: AccessDenied"))
    @patch("cloud_credentials.leaf_keys.b2.B2Api")
    def test_does_not_cache_a_credential_that_fails_verification(self, mock_api_cls, _mock_verify):
        api = mock_api_cls.return_value
        api.get_bucket_by_name.return_value = MagicMock(id_="bkt")
        api.create_key.return_value = MagicMock(spec=FullApplicationKey, id_="KEY_ID", application_key="APP_KEY")

        ok = snap.mint_b2()

        assert not ok
        assert snap.read_cache(snap.CACHE_B2_ACCESS) is None

    def test_skips_if_already_cached(self, vault):
        vault.seed(snap.CACHE_B2_ACCESS, "existing-id")
        vault.seed(snap.CACHE_B2_SECRET, "existing-secret")

        ok = snap.mint_b2()

        assert ok


class TestRotateB2:
    @pytest.fixture(autouse=True)
    def _seeded(self, vault):
        vault.seed("_rotation-key-backblaze-b2-key-id", "rot-id", category="rotation")
        vault.seed("_rotation-key-backblaze-b2-application-key", "rot-key", category="rotation")
        vault.seed("backblaze-b2-region", "us-west-004")
        vault.seed(snap.CACHE_B2_ACCESS, "OLD_KEY_ID")
        vault.seed(snap.CACHE_B2_SECRET, "old-secret")

    @patch.object(snap, "verify_leaf_via_rclone", return_value=(True, "PutObject succeeded"))
    @patch("cloud_credentials.leaf_keys.b2.B2Api")
    def test_verifies_new_key_before_revoking_the_old_one(self, mock_api_cls, _mock_verify):
        api = mock_api_cls.return_value
        api.get_bucket_by_name.return_value = MagicMock(id_="bkt")
        api.create_key.return_value = MagicMock(spec=FullApplicationKey, id_="NEW_KEY_ID", application_key="NEW_APP_KEY")

        ok = snap.rotate_b2()

        assert ok
        api.session.delete_key.assert_called_once_with("OLD_KEY_ID")
        assert snap.read_cache(snap.CACHE_B2_ACCESS) == "NEW_KEY_ID"

    @patch.object(snap, "verify_leaf_via_rclone", return_value=(False, "PutObject failed: AccessDenied"))
    @patch("cloud_credentials.leaf_keys.b2.B2Api")
    def test_leaves_old_key_untouched_when_new_one_fails_verification(self, mock_api_cls, _mock_verify):
        api = mock_api_cls.return_value
        api.get_bucket_by_name.return_value = MagicMock(id_="bkt")
        api.create_key.return_value = MagicMock(spec=FullApplicationKey, id_="NEW_KEY_ID", application_key="NEW_APP_KEY")

        ok = snap.rotate_b2()

        assert not ok
        api.session.delete_key.assert_not_called()
        assert snap.read_cache(snap.CACHE_B2_ACCESS) == "OLD_KEY_ID", "old credential must stay live and cached until a new one actually verifies"


class TestRotateR2:
    @pytest.fixture(autouse=True)
    def _seeded(self, vault):
        vault.seed("_rotation-key-cloudflare-r2-token", "admin-token", category="rotation")
        vault.seed("cloudflare-r2-account-id", "acct123")
        vault.seed(snap.CACHE_R2_ACCESS, "OLD_TOKEN_ID")
        vault.seed(snap.CACHE_R2_SECRET, "old-secret")

    @patch.object(snap, "r2_delete_token")
    @patch.object(snap, "verify_leaf_via_rclone", return_value=(True, "PutObject succeeded"))
    @patch.object(snap, "r2_permission_group_ids", return_value={"Workers R2 Storage Bucket Item Write": "grp-write"})
    def test_verifies_new_token_before_revoking_the_old_one(self, _mock_groups, _mock_verify, mock_delete, session_class):
        session = session_class.return_value
        session.post.return_value = response(json_body={"success": True, "result": {"id": "NEW_TOKEN_ID", "value": "new-value"}})

        ok = snap.rotate_r2()

        assert ok
        mock_delete.assert_called_once_with(session, "acct123", "OLD_TOKEN_ID")
        assert snap.read_cache(snap.CACHE_R2_ACCESS) == "NEW_TOKEN_ID"

    @patch.object(snap, "r2_delete_token")
    @patch.object(snap, "verify_leaf_via_rclone", return_value=(False, "PutObject failed: AccessDenied"))
    @patch.object(snap, "r2_permission_group_ids", return_value={"Workers R2 Storage Bucket Item Write": "grp-write"})
    def test_leaves_old_token_untouched_when_new_one_fails_verification(self, _mock_groups, _mock_verify, mock_delete, session_class):
        session = session_class.return_value
        session.post.return_value = response(json_body={"success": True, "result": {"id": "NEW_TOKEN_ID", "value": "new-value"}})

        ok = snap.rotate_r2()

        assert not ok
        mock_delete.assert_not_called()
        assert snap.read_cache(snap.CACHE_R2_ACCESS) == "OLD_TOKEN_ID", "old credential must stay live and cached until a new one actually verifies"
