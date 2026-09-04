"""Unit tests for cloud_credentials.leaf_keys.oci.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from _base import RotationTestBase
from cloud_credentials.leaf_keys import oci


class OciRotationTests(RotationTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-oci-user-ocid", "ocid1.user.oc1..rot")
        self.seed("_rotation-key-oci-fingerprint", "aa:bb")
        self.seed("_rotation-key-oci-tenancy-ocid", "ocid1.tenancy.oc1..t")
        self.seed("_rotation-key-oci-region", "us-ashburn-1")
        (self.tmp / "_rotation-key-oci-private-key.pem").write_text("-----BEGIN-----")
        self.seed("_oci-leaf-user-ocid-read", "ocid1.user.oc1..readleaf")
        self.seed("oci-namespace", "mynamespace")
        self.seed("oci-region", "us-ashburn-1")
        self.seed("oci-read-access-key", "OLD_OCID")
        self.seed("oci-read-secret-key", "OLD_SECRET")

    @patch.object(oci, "verify_leaf_via_rclone", return_value=(True, "ok"))
    @patch.object(oci, "OCISigner")
    @patch.object(oci.requests, "Session")
    def test_successful_rotation_deletes_old_secret_key(self, mock_session_cls, mock_signer, mock_verify):
        session = mock_session_cls.return_value
        session.post.return_value = MagicMock(raise_for_status=lambda: None, json=lambda: {"id": "NEW_OCID", "key": "NEW_SECRET"})
        session.delete.return_value = MagicMock(raise_for_status=lambda: None)

        ok = oci.rotate_oci(["read"])

        self.assertTrue(ok)
        mock_verify.assert_called_once_with(
            "NEW_OCID",
            "NEW_SECRET",
            "https://mynamespace.compat.objectstorage.us-ashburn-1.oraclecloud.com",
            "us-ashburn-1",
            oci.OCI_BUCKET,
            "read",
        )
        session.delete.assert_called_once()
        self.assertIn("OLD_OCID", session.delete.call_args.args[0])
        self.assertEqual((self.tmp / "oci-read-access-key").read_text(), "NEW_OCID")
        self.assertEqual((self.tmp / "oci-read-secret-key").read_text(), "NEW_SECRET")
        # Self-tracked expiry (see ADR 0015) only works if a rotation
        # actually refreshes the timestamp, not just the key material.
        self.assertTrue((self.tmp / "oci-read-created-at").exists())

    @patch.object(oci, "verify_leaf_via_rclone", return_value=(False, "permission denied"))
    @patch.object(oci, "OCISigner")
    @patch.object(oci.requests, "Session")
    def test_failed_verification_never_calls_delete(self, mock_session_cls, mock_signer, mock_verify):
        session = mock_session_cls.return_value
        session.post.return_value = MagicMock(raise_for_status=lambda: None, json=lambda: {"id": "NEW_OCID", "key": "NEW_SECRET"})

        ok = oci.rotate_oci(["read"])

        self.assertFalse(ok)
        session.delete.assert_not_called()
        self.assertEqual((self.tmp / "oci-read-access-key").read_text(), "OLD_OCID")


if __name__ == "__main__":
    import unittest

    unittest.main()
