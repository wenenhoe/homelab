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


class AuditLocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(audit_secrets, "SECRETS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

        # Deliberately a separate directory from SECRETS_DIR - audit_local()
        # scans every file under SECRETS_DIR, so a registry file placed
        # inside it would incorrectly show up as its own orphan.
        registry_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(registry_dir, ignore_errors=True))
        registry_path = registry_dir / "secrets_registry.yaml"
        registry_path.write_text("secrets_registry:\n  cloudflare-r2-write-access-key: {}\n  cloudflare-r2-write-secret-key: {}\n")
        registry_patcher = patch.object(audit_secrets, "REGISTRY_PATH", registry_path)
        registry_patcher.start()
        self.addCleanup(registry_patcher.stop)

    def seed(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)

    def test_r2_rotation_token_is_not_flagged_as_an_orphan(self):
        """Regression test: _rotation-key-cloudflare-r2-token was
        missing from KNOWN_INTERNAL_PATTERNS despite being a real,
        actively-used cache file (r2_rotation_token() reads it,
        cache_r2_rotation_token()/rotate_r2_rotation_token() write it) -
        a false-positive orphan that predates the OCI SCIM migration."""
        self.seed("_rotation-key-cloudflare-r2-token", "shh")
        self.seed("cloudflare-r2-write-access-key", "abc")
        self.seed("cloudflare-r2-write-secret-key", "def")

        with patch("sys.stdout") as mock_stdout:
            audit_secrets.audit_local()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        self.assertNotIn("not referenced by current config", printed)
        self.assertIn("all match a current registry/internal entry", printed)

    def test_genuinely_unreferenced_file_is_flagged(self):
        self.seed("cloudflare-r2-write-access-key", "abc")
        self.seed("cloudflare-r2-write-secret-key", "def")
        self.seed("some-leftover-from-a-naming-change", "stale")

        with patch("sys.stdout") as mock_stdout:
            audit_secrets.audit_local()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        self.assertIn("some-leftover-from-a-naming-change", printed)
        self.assertIn("1 file(s) not referenced", printed)

    def test_all_current_oci_scim_cache_keys_are_known(self):
        for name in [
            "_rotation-key-oci-domain-url",
            "_rotation-key-oci-client-id",
            "_rotation-key-oci-client-secret",
            "_rotation-key-oci-app-id",
            "_rotation-key-oci-created-at",
            "_oci-leaf-user-ocid-write",
            "_oci-leaf-user-ocid-read",
            "oci-write-scim-id",
            "oci-read-scim-id",
        ]:
            self.seed(name, "x")
        self.seed("cloudflare-r2-write-access-key", "abc")
        self.seed("cloudflare-r2-write-secret-key", "def")

        with patch("sys.stdout") as mock_stdout:
            audit_secrets.audit_local()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        self.assertIn("all match a current registry/internal entry", printed)


if __name__ == "__main__":
    unittest.main()
