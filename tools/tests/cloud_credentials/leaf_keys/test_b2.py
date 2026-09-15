"""Unit tests for cloud_credentials.leaf_keys.b2.

Run via `uv run pytest tools/tests/ -v`. Every B2 call is mocked at
the b2sdk B2Api boundary (Stage 3, docs/projects/cloud-credentials-hardening.md)
- nothing here talks to a real account.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from _base import RotationTestBase
from b2sdk.v2 import FullApplicationKey
from b2sdk.v2.exception import Unauthorized
from cloud_credentials.expiry import QUARTERLY_SECONDS
from cloud_credentials.leaf_keys import b2


def _full_application_key(access_key: str, secret_key: str) -> MagicMock:
    # spec=FullApplicationKey, not a bare MagicMock: the real class
    # stores the key id as .id_, not .application_key_id (the
    # constructor's own parameter name) - a bare MagicMock would accept
    # either name silently, and this exact mismatch shipped once
    # already (caught only by a live spike, not by these tests). spec
    # makes a typo here raise immediately instead of hiding it.
    return MagicMock(spec=FullApplicationKey, id_=access_key, application_key=secret_key)


class B2RotationTests(RotationTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-backblaze-b2-key-id", "rot-id", category="rotation")
        self.seed("_rotation-key-backblaze-b2-application-key", "rot-key", category="rotation")
        self.seed("backblaze-b2-region", "us-west-004")
        self.seed("backblaze-b2-write-access-key", "OLD_ACCESS")
        self.seed("backblaze-b2-write-secret-key", "OLD_SECRET")

    @patch.object(b2, "verify_leaf_via_rclone", return_value=(True, "ok"))
    @patch.object(b2, "B2Api")
    def test_successful_rotation_revokes_old_key_and_caches_new_one(self, mock_api_cls, mock_verify):
        api = mock_api_cls.return_value
        api.get_bucket_by_name.return_value = MagicMock(id_="bkt")
        api.create_key.return_value = _full_application_key("NEW_ACCESS", "NEW_SECRET")

        ok = b2.rotate_b2(["write"])

        self.assertTrue(ok)
        # Region matters, not just endpoint: a missing/wrong region is
        # exactly the live bug this caught (OCI 403 SignatureDoesNotMatch
        # outside the tenancy's home region) — assert the actual call
        # arguments, not just that verify ran.
        mock_verify.assert_called_once_with("NEW_ACCESS", "NEW_SECRET", "https://s3.us-west-004.backblazeb2.com", "us-west-004", b2.B2_BUCKET, "write")
        # The old key's delete call must happen, and only after verify passed.
        api.session.delete_key.assert_called_once_with("OLD_ACCESS")
        self.assertEqual(self.get("backblaze-b2-write-access-key"), "NEW_ACCESS")
        self.assertEqual(self.get("backblaze-b2-write-secret-key"), "NEW_SECRET")
        # The actual point of this test: every new leaf key must request
        # native expiry, not just get created.
        self.assertEqual(api.create_key.call_args.kwargs["valid_duration_seconds"], QUARTERLY_SECONDS)

    @patch.object(b2, "verify_leaf_via_rclone", return_value=(False, "auth failed"))
    @patch.object(b2, "B2Api")
    def test_failed_verification_leaves_old_key_untouched(self, mock_api_cls, mock_verify):
        api = mock_api_cls.return_value
        api.get_bucket_by_name.return_value = MagicMock(id_="bkt")
        api.create_key.return_value = _full_application_key("NEW_ACCESS", "NEW_SECRET")

        ok = b2.rotate_b2(["write"])

        self.assertFalse(ok)
        api.session.delete_key.assert_not_called()
        # Cache must be untouched — the old, still-valid key stays authoritative.
        self.assertEqual(self.get("backblaze-b2-write-access-key"), "OLD_ACCESS")
        self.assertEqual(self.get("backblaze-b2-write-secret-key"), "OLD_SECRET")

    @patch.object(b2, "verify_leaf_via_rclone", return_value=(True, "ok"))
    @patch.object(b2, "B2Api")
    def test_revoke_failure_is_reported_not_raised(self, mock_api_cls, mock_verify):
        api = mock_api_cls.return_value
        api.get_bucket_by_name.return_value = MagicMock(id_="bkt")
        api.create_key.return_value = _full_application_key("NEW_ACCESS", "NEW_SECRET")
        api.session.delete_key.side_effect = Unauthorized("", "unauthorized")

        ok = b2.rotate_b2(["write"])

        # Same contract as OCI/R2's rotate_*: revoke failure is a
        # warning, not a reason to discard an already-verified new key.
        self.assertTrue(ok)
        self.assertEqual(self.get("backblaze-b2-write-access-key"), "NEW_ACCESS")


if __name__ == "__main__":
    import unittest

    unittest.main()
