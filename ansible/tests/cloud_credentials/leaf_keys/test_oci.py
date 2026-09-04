"""Unit tests for cloud_credentials.leaf_keys.oci.

Run via `uv run pytest ansible/tests/ -v`. Every HTTP call is mocked;
nothing here talks to a real tenancy.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from _base import RotationTestBase
from cloud_credentials.leaf_keys import oci


def _scim_key_response(scim_id="NEW_SCIM_ID", access_key="NEW_ACCESS", secret_key="NEW_SECRET"):  # noqa: S107 - test fixture, not a real credential
    return MagicMock(raise_for_status=lambda: None, json=lambda: {"id": scim_id, "accessKey": access_key, "secretKey": secret_key})


class OciRotationTests(RotationTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-oci-domain-url", "https://idcs-example.identity.oraclecloud.com")
        self.seed("_rotation-key-oci-client-id", "client-123")
        self.seed("_rotation-key-oci-client-secret", "shh")
        self.seed("_oci-leaf-user-ocid-read", "ocid1.user.oc1..readleaf")
        self.seed("_oci-leaf-user-ocid-write", "ocid1.user.oc1..writeleaf")
        self.seed("oci-namespace", "mynamespace")
        self.seed("oci-region", "us-ashburn-1")
        self.seed("oci-read-access-key", "OLD_ACCESS")
        self.seed("oci-read-secret-key", "OLD_SECRET")
        self.seed("oci-read-scim-id", "OLD_SCIM_ID")

    @patch.object(oci, "verify_leaf_via_rclone", return_value=(True, "ok"))
    @patch.object(oci.requests, "post")
    @patch.object(oci.requests, "Session")
    def test_successful_rotation_deletes_old_secret_key(self, mock_session_cls, mock_token_post, mock_verify):
        mock_token_post.return_value = MagicMock(raise_for_status=lambda: None, json=lambda: {"access_token": "tok"})
        session = mock_session_cls.return_value
        session.post.return_value = _scim_key_response()
        session.delete.return_value = MagicMock(raise_for_status=lambda: None)

        ok = oci.rotate_oci(["read"])

        self.assertTrue(ok)
        mock_verify.assert_called_once_with(
            "NEW_ACCESS",
            "NEW_SECRET",
            "https://mynamespace.compat.objectstorage.us-ashburn-1.oraclecloud.com",
            "us-ashburn-1",
            oci.OCI_BUCKET,
            "read",
        )
        session.delete.assert_called_once()
        self.assertIn("OLD_SCIM_ID", session.delete.call_args.args[0])
        self.assertEqual((self.tmp / "oci-read-access-key").read_text(), "NEW_ACCESS")
        self.assertEqual((self.tmp / "oci-read-secret-key").read_text(), "NEW_SECRET")
        self.assertEqual((self.tmp / "oci-read-scim-id").read_text(), "NEW_SCIM_ID")
        # expiresOn is native now (see ADR 0016) - no self-tracked
        # -created-at cache file should exist for a SCIM-created key.
        self.assertFalse((self.tmp / "oci-read-created-at").exists())

    @patch.object(oci, "verify_leaf_via_rclone", return_value=(False, "permission denied"))
    @patch.object(oci.requests, "post")
    @patch.object(oci.requests, "Session")
    def test_failed_verification_never_calls_delete(self, mock_session_cls, mock_token_post, mock_verify):
        mock_token_post.return_value = MagicMock(raise_for_status=lambda: None, json=lambda: {"access_token": "tok"})
        session = mock_session_cls.return_value
        session.post.return_value = _scim_key_response()

        ok = oci.rotate_oci(["read"])

        self.assertFalse(ok)
        session.delete.assert_not_called()
        self.assertEqual((self.tmp / "oci-read-access-key").read_text(), "OLD_ACCESS")
        self.assertEqual((self.tmp / "oci-read-scim-id").read_text(), "OLD_SCIM_ID")

    @patch.object(oci.requests, "post")
    @patch.object(oci.requests, "Session")
    def test_create_uses_user_ocid_field_not_value(self, mock_session_cls, mock_token_post):
        mock_token_post.return_value = MagicMock(raise_for_status=lambda: None, json=lambda: {"access_token": "tok"})
        session = mock_session_cls.return_value
        session.post.return_value = _scim_key_response()

        oci.create_oci()

        # Both leaves get created since neither is cached in setUp
        # beyond "read"'s pre-existing key - "write" starts empty.
        write_call_bodies = [c.kwargs["json"] for c in session.post.call_args_list]
        self.assertTrue(all(body["user"].keys() == {"ocid"} for body in write_call_bodies))


if __name__ == "__main__":
    import unittest

    unittest.main()
