"""Unit tests for audit_secrets.audit_oci.

Run via `uv run pytest ansible/tests/ -v`. Every SCIM call is mocked;
nothing here talks to a real tenancy. audit_secrets.py has its own
independent SECRETS_DIR/cached() (it's a standalone top-level script,
not part of the cloud_credentials package), so this patches
audit_secrets.SECRETS_DIR directly rather than cloud_credentials.cache.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import audit_secrets


def _mock_response(status_code: int, json_body: dict | None = None):
    resp = MagicMock(status_code=status_code, text=str(json_body))
    resp.json.return_value = json_body or {}
    resp.raise_for_status = MagicMock() if status_code < 400 else MagicMock(side_effect=Exception(str(status_code)))
    return resp


class AuditOciTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(audit_secrets, "SECRETS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)

    @patch("cloud_credentials.rotation_keys.oci_scim.oci_scim_session", side_effect=SystemExit(1))
    def test_no_scim_credentials_returns_gracefully_without_crashing(self, mock_session):
        audit_secrets.audit_oci()  # must not raise

    @patch("cloud_credentials.rotation_keys.oci_scim.oci_scim_session")
    def test_leaf_without_cached_user_ocid_is_skipped(self, mock_session):
        # Neither _oci-leaf-user-ocid-write nor -read seeded.
        session = MagicMock()
        mock_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        with patch("sys.stdout") as mock_stdout:
            audit_secrets.audit_oci()

        session.get.assert_not_called()
        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        self.assertIn("no cached user OCID, skipping", printed)

    @patch("cloud_credentials.rotation_keys.oci_scim.oci_scim_session")
    def test_active_key_matches_cached_scim_id_orphan_does_not(self, mock_session):
        self.seed("_oci-leaf-user-ocid-write", "ocid1.user.oc1..writeleaf")
        self.seed("oci-write-scim-id", "scim-active")
        session = MagicMock()

        def get_side_effect(url, params=None):
            if "user.ocid eq" in params.get("filter", ""):
                return _mock_response(
                    200,
                    {
                        "Resources": [
                            {"id": "scim-active", "accessKey": "ACCESS-ACTIVE", "status": "ACTIVE", "meta": {"created": "2026-01-01T00:00:00Z"}},
                            {"id": "scim-orphan", "accessKey": "ACCESS-ORPHAN", "status": "ACTIVE", "meta": {"created": "2025-01-01T00:00:00Z"}},
                        ]
                    },
                )
            return _mock_response(200, {"Resources": []})

        session.get.side_effect = get_side_effect
        mock_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        with patch("sys.stdout") as mock_stdout:
            audit_secrets.audit_oci()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        self.assertIn("scim_id=scim-active", printed)
        self.assertIn("ACTIVE (matches cache)", printed)
        self.assertIn("scim_id=scim-orphan", printed)
        self.assertIn("ORPHAN", printed)
        self.assertIn("DELETE https://idcs-example.identity.oraclecloud.com/admin/v1/CustomerSecretKeys/scim-orphan", printed)

    @patch("cloud_credentials.rotation_keys.oci_scim.oci_scim_session")
    def test_filter_query_scoped_to_the_correct_leaf_user(self, mock_session):
        self.seed("_oci-leaf-user-ocid-write", "ocid1.user.oc1..writeleaf")
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"Resources": []})
        mock_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        audit_secrets.audit_oci()

        sent_filter = session.get.call_args.kwargs["params"]["filter"]
        self.assertIn("ocid1.user.oc1..writeleaf", sent_filter)


if __name__ == "__main__":
    unittest.main()
