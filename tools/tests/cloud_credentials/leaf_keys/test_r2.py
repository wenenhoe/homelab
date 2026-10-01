"""Unit tests for cloud_credentials.leaf_keys.r2.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from cloud_credentials.expiry import QUARTERLY_DAYS
from cloud_credentials.leaf_keys import r2


class TestR2RotationToken:
    """Covers caching the R2 admin token — the actual change requested:
    stop re-prompting for a value that was always the same human-created
    Console token."""

    def test_prompts_and_caches_when_nothing_cached(self, vault):
        with patch.object(r2.getpass, "getpass", return_value="cf-token-value") as mock_prompt:
            token = r2.r2_rotation_token()
        mock_prompt.assert_called_once()
        assert token == "cf-token-value"
        assert vault.get("_rotation-key-cloudflare-r2-token", category="rotation") == "cf-token-value"

    def test_uses_cache_without_prompting_on_subsequent_calls(self, vault):
        vault.seed("_rotation-key-cloudflare-r2-token", "cached-token-value", category="rotation")
        with patch.object(r2.getpass, "getpass") as mock_prompt:
            token = r2.r2_rotation_token()
        mock_prompt.assert_not_called()
        assert token == "cached-token-value"


def _permission_groups_response():
    return MagicMock(
        json=lambda: {
            "success": True,
            "result": [
                {"name": "Workers R2 Storage Bucket Item Write", "id": "grp-write"},
                {"name": "Workers R2 Storage Bucket Item Read", "id": "grp-read"},
            ],
        }
    )


def _create_token_response(token_id, token_value):
    return MagicMock(json=lambda: {"success": True, "result": {"id": token_id, "value": token_value}})


class TestR2Rotation:
    @pytest.fixture(autouse=True)
    def _seeded(self, vault):
        vault.seed("_rotation-key-cloudflare-r2-token", "admin-token", category="rotation")
        vault.seed("cloudflare-r2-account-id", "acct123")
        vault.seed("cloudflare-r2-write-access-key", "OLD_TOKEN_ID")
        vault.seed("cloudflare-r2-write-secret-key", "old_secret_hash")

    @patch.object(r2, "verify_leaf_via_rclone", return_value=(True, "ok"))
    @patch.object(r2.requests, "Session")
    def test_successful_rotation_deletes_old_token_and_caches_new_one(self, mock_session_cls, mock_verify, vault):
        session = mock_session_cls.return_value
        session.get.return_value = _permission_groups_response()
        session.post.return_value = _create_token_response("NEW_TOKEN_ID", "new-token-value")
        session.delete.return_value = MagicMock(json=lambda: {"success": True})

        ok = r2.rotate_r2(["write"])

        assert ok
        mock_verify.assert_called_once_with(
            "NEW_TOKEN_ID",
            hashlib.sha256(b"new-token-value").hexdigest(),
            "https://acct123.r2.cloudflarestorage.com",
            "auto",
            r2.R2_BUCKET,
            "write",
        )
        session.delete.assert_called_once()
        assert "OLD_TOKEN_ID" in session.delete.call_args.args[0]
        assert vault.get("cloudflare-r2-write-access-key") == "NEW_TOKEN_ID"
        # Every new leaf token must request native expiry (see ADR 0015)
        create_call = session.post.call_args
        expires_on = create_call.kwargs["json"]["expires_on"]
        assert re.search(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", expires_on)
        days_out = (datetime.strptime(expires_on, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) - datetime.now(UTC)).days
        assert days_out == QUARTERLY_DAYS - 1  # -1: truncated days, not a bug in the code under test

    @patch.object(r2, "verify_leaf_via_rclone", return_value=(False, "denied"))
    @patch.object(r2.requests, "Session")
    def test_failed_verification_leaves_old_token_untouched(self, mock_session_cls, mock_verify, vault):
        session = mock_session_cls.return_value
        session.get.return_value = _permission_groups_response()
        session.post.return_value = _create_token_response("NEW_TOKEN_ID", "new-token-value")

        ok = r2.rotate_r2(["write"])

        assert not ok
        session.delete.assert_not_called()
        assert vault.get("cloudflare-r2-write-access-key") == "OLD_TOKEN_ID"
