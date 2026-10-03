"""Unit tests for cloud_credentials.leaf_keys.b2.

Run via `uv run pytest tools/tests/ -v`. Every B2 call is mocked at
the b2sdk B2Api boundary (docs/decisions/0029-cloud-provider-api-client-library/revision-000.md)
- nothing here talks to a real account.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from _b2_objects import bucket, full_application_key
from b2sdk.v2.exception import Unauthorized
from cloud_credentials.expiry import QUARTERLY_SECONDS
from cloud_credentials.leaf_keys import b2


class TestB2Rotation:
    @pytest.fixture(autouse=True)
    def _seeded(self, vault):
        vault.seed("_rotation-key-backblaze-b2-key-id", "rot-id", category="rotation")
        vault.seed("_rotation-key-backblaze-b2-application-key", "rot-key", category="rotation")
        vault.seed("backblaze-b2-region", "us-west-004")
        vault.seed("backblaze-b2-write-access-key", "OLD_ACCESS")
        vault.seed("backblaze-b2-write-secret-key", "OLD_SECRET")

    @patch.object(b2, "verify_leaf_via_rclone", return_value=(True, "ok"), autospec=True)
    @patch.object(b2, "B2Api", autospec=True)
    def test_successful_rotation_revokes_old_key_and_caches_new_one(self, mock_api_cls, mock_verify, vault, b2_api):
        api = mock_api_cls.return_value = b2_api
        api.get_bucket_by_name.return_value = bucket(api)
        api.create_key.return_value = full_application_key("NEW_ACCESS", "NEW_SECRET")

        ok = b2.rotate_b2(["write"])

        assert ok
        # Region matters, not just endpoint: a missing or wrong region
        # fails with an OCI 403 SignatureDoesNotMatch outside the
        # tenancy's home region — assert the actual call arguments, not
        # just that verify ran.
        mock_verify.assert_called_once_with("NEW_ACCESS", "NEW_SECRET", "https://s3.us-west-004.backblazeb2.com", "us-west-004", b2.B2_BUCKET, "write")
        # The old key's delete call must happen, and only after verify passed.
        api.session.delete_key.assert_called_once_with("OLD_ACCESS")
        assert vault.get("backblaze-b2-write-access-key") == "NEW_ACCESS"
        assert vault.get("backblaze-b2-write-secret-key") == "NEW_SECRET"
        # The actual point of this test: every new leaf key must request
        # native expiry, not just get created.
        assert api.create_key.call_args.kwargs["valid_duration_seconds"] == QUARTERLY_SECONDS

    @patch.object(b2, "verify_leaf_via_rclone", return_value=(False, "auth failed"), autospec=True)
    @patch.object(b2, "B2Api", autospec=True)
    def test_failed_verification_leaves_old_key_untouched(self, mock_api_cls, mock_verify, vault, b2_api):
        api = mock_api_cls.return_value = b2_api
        api.get_bucket_by_name.return_value = bucket(api)
        api.create_key.return_value = full_application_key("NEW_ACCESS", "NEW_SECRET")

        ok = b2.rotate_b2(["write"])

        assert not ok
        api.session.delete_key.assert_not_called()
        # Cache must be untouched — the old, still-valid key stays authoritative.
        assert vault.get("backblaze-b2-write-access-key") == "OLD_ACCESS"
        assert vault.get("backblaze-b2-write-secret-key") == "OLD_SECRET"

    @patch.object(b2, "verify_leaf_via_rclone", return_value=(True, "ok"), autospec=True)
    @patch.object(b2, "B2Api", autospec=True)
    def test_revoke_failure_is_reported_not_raised(self, mock_api_cls, mock_verify, vault, b2_api):
        api = mock_api_cls.return_value = b2_api
        api.get_bucket_by_name.return_value = bucket(api)
        api.create_key.return_value = full_application_key("NEW_ACCESS", "NEW_SECRET")
        api.session.delete_key.side_effect = Unauthorized("", "unauthorized")

        ok = b2.rotate_b2(["write"])

        # Same contract as OCI/R2's rotate_*: revoke failure is a
        # warning, not a reason to discard an already-verified new key.
        assert ok
        assert vault.get("backblaze-b2-write-access-key") == "NEW_ACCESS"
