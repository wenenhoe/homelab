"""Unit tests for audit_secrets.audit_oci/audit_local.

Run via `uv run pytest ansible/tests/ -v`. Every SCIM/Vault call is
mocked; nothing here talks to a real tenancy or a real OpenBao.
audit_secrets.py's cached() reads through cloud_credentials'
own LEGACY_CACHE_KEYS-mapped modules (Vault-backed, since Track A
stage 5) - AuditOciTests patches audit_secrets.cached directly rather
than seeding files, since there's no longer a local file it reads.
audit_local() is a different concern (scanning SECRETS_DIR for orphan
files left on disk), so AuditLocalTests still seeds real files there.
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
        self._cached_values: dict[str, str] = {}
        patcher = patch.object(audit_secrets, "cached", side_effect=lambda name: self._cached_values.get(name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed(self, name: str, value: str) -> None:
        self._cached_values[name] = value

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


class CachedDispatchTests(unittest.TestCase):
    """cached() itself: confirms it reads through the correct
    LEGACY_CACHE_KEYS-mapped module rather than any local file."""

    def test_reads_via_the_names_own_module(self):
        with patch.object(audit_secrets._CACHE_MODULE_BY_NAME["cloudflare-r2-account-id"], "read_cache", return_value="acct-123") as mock_read:
            self.assertEqual(audit_secrets.cached("cloudflare-r2-account-id"), "acct-123")
        mock_read.assert_called_once_with("cloudflare-r2-account-id")

    def test_unknown_name_raises_instead_of_silently_returning_none(self):
        with self.assertRaises(KeyError):
            audit_secrets.cached("not-a-real-cloud-credentials-name")


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
        self.assertIn("all belong to a permanent file-cache entry", printed)

    def test_genuinely_unreferenced_file_is_flagged(self):
        self.seed("cloudflare-r2-write-access-key", "abc")
        self.seed("cloudflare-r2-write-secret-key", "def")
        self.seed("some-leftover-from-a-naming-change", "stale")

        with patch("sys.stdout") as mock_stdout:
            audit_secrets.audit_local()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        self.assertIn("some-leftover-from-a-naming-change", printed)
        self.assertIn("1 file(s) not referenced", printed)

    def test_vault_backed_entry_with_a_stray_local_file_is_flagged_separately_from_an_orphan(self):
        """Regression test: a controller that predates the entry's move
        to Vault (Track A stage 4 for most entries, stage 5/6 for cloud
        credentials) can have a stray, never-since-read local file for
        a registry entry that has a vault_scope. That's a distinct
        finding from a genuine orphan - the name IS known, it's just
        the wrong mechanism now - found via the stage 6 cutover drill
        surfacing exactly this on a real controller."""
        registry_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(registry_dir, ignore_errors=True))
        registry_path = registry_dir / "secrets_registry.yaml"
        registry_path.write_text("secrets_registry:\n  lldap-jwt-secret: { format: hex, length: 32, vault_scope: hosts/security }\n")
        registry_patcher = patch.object(audit_secrets, "REGISTRY_PATH", registry_path)
        registry_patcher.start()
        self.addCleanup(registry_patcher.stop)

        self.seed("lldap-jwt-secret", "stale-pre-vault-value")

        with patch("sys.stdout") as mock_stdout:
            audit_secrets.audit_local()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        self.assertIn("lldap-jwt-secret", printed)
        self.assertIn("vault_scope: hosts/security", printed)
        self.assertIn("1 file(s) for a Vault-backed entry", printed)
        # Must not also be reported as a plain orphan - it's a known name.
        self.assertNotIn("not referenced by current config at all", printed)

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
        self.assertIn("all belong to a permanent file-cache entry", printed)


class AuditB2Tests(unittest.TestCase):
    """audit_b2()'s active-key classification. Regression coverage for
    two real bugs found running audit_secrets.py --provider all against
    a live account (Track A stage 6's cutover drill): the openbao
    snapshot write leaf was cached in Vault but never checked against,
    and the break-glass readonly key (ADR 0017) can never match a cache
    lookup since it's never cached anywhere by design."""

    def setUp(self):
        self._cached_values = {
            "_rotation-key-backblaze-b2-key-id": "rotation-key-id",
            "_rotation-key-backblaze-b2-application-key": "rotation-app-key",
            "backblaze-b2-write-access-key": "write-key-id",
            "backblaze-b2-read-access-key": "read-key-id",
            "backblaze-b2-openbao-snapshot-write-access-key": "snapshot-write-key-id",
        }
        patcher = patch.object(audit_secrets, "cached", side_effect=lambda name: self._cached_values.get(name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _mock_b2_session(self, keys):
        auth_resp = _mock_response(200, {"authorizationToken": "tok", "apiUrl": "https://api.example.com", "accountId": "acct"})
        list_resp = _mock_response(200, {"keys": keys})
        session = MagicMock()
        session.get.return_value = list_resp
        return auth_resp, session

    def test_openbao_snapshot_write_leaf_is_active_not_orphan(self):
        auth_resp, session = self._mock_b2_session([{"applicationKeyId": "snapshot-write-key-id", "keyName": "openbao-snapshot-write"}])
        with (
            patch("audit_secrets.requests.get", return_value=auth_resp),
            patch("audit_secrets.requests.Session", return_value=session),
            patch("sys.stdout") as mock_stdout,
        ):
            audit_secrets.audit_b2()
        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        self.assertIn("ACTIVE (openbao snapshot write leaf)", printed)
        self.assertNotIn("ORPHAN", printed)

    def test_openbao_snapshot_readonly_is_active_matched_by_name(self):
        auth_resp, session = self._mock_b2_session([{"applicationKeyId": "some-other-id", "keyName": "openbao-snapshot-readonly"}])
        with (
            patch("audit_secrets.requests.get", return_value=auth_resp),
            patch("audit_secrets.requests.Session", return_value=session),
            patch("sys.stdout") as mock_stdout,
        ):
            audit_secrets.audit_b2()
        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        self.assertIn("ACTIVE (break-glass restore key", printed)
        self.assertNotIn("ORPHAN", printed)

    def test_genuinely_unknown_key_is_still_flagged_orphan(self):
        auth_resp, session = self._mock_b2_session([{"applicationKeyId": "mystery-id", "keyName": "some-leftover-key"}])
        with (
            patch("audit_secrets.requests.get", return_value=auth_resp),
            patch("audit_secrets.requests.Session", return_value=session),
            patch("sys.stdout") as mock_stdout,
        ):
            audit_secrets.audit_b2()
        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        self.assertIn("mystery-id", printed)
        self.assertIn("ORPHAN", printed)


class AuditR2Tests(unittest.TestCase):
    """audit_r2()'s active-token classification - same two bugs as
    AuditB2Tests, plus a third: the token-name filter excluded both
    openbao-snapshot tokens entirely (neither matches the
    homelab-cloud-sync-r2- prefix), so they never appeared in the audit
    at all, orphan or not."""

    def setUp(self):
        self._cached_values = {
            "cloudflare-r2-account-id": "acct-123",
            "cloudflare-r2-write-access-key": "write-token-id",
            "cloudflare-r2-read-access-key": "read-token-id",
            "cloudflare-r2-openbao-snapshot-write-access-key": "snapshot-write-token-id",
        }
        patcher = patch.object(audit_secrets, "cached", side_effect=lambda name: self._cached_values.get(name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run_with_tokens(self, tokens):
        resp = _mock_response(200, {"success": True, "result": tokens})
        session = MagicMock()
        session.get.return_value = resp
        with (
            patch("audit_secrets.requests.Session", return_value=session),
            patch("audit_secrets.getpass.getpass", return_value="admin-token"),
            patch("sys.stdout") as mock_stdout,
        ):
            audit_secrets.audit_r2()
        return "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)

    def test_openbao_snapshot_write_token_is_included_and_active(self):
        printed = self._run_with_tokens([{"id": "snapshot-write-token-id", "name": "openbao-snapshot-write", "status": "active"}])
        self.assertIn("ACTIVE (openbao snapshot write leaf)", printed)
        self.assertNotIn("ORPHAN", printed)

    def test_openbao_snapshot_readonly_token_is_included_and_active(self):
        printed = self._run_with_tokens([{"id": "some-other-id", "name": "openbao-snapshot-readonly", "status": "active"}])
        self.assertIn("ACTIVE (break-glass restore key", printed)
        self.assertNotIn("ORPHAN", printed)

    def test_token_outside_known_naming_is_excluded_from_the_count_entirely(self):
        # Not a regression target of this fix - documents the existing
        # filter's own behavior so a future change to it is deliberate.
        printed = self._run_with_tokens([{"id": "unrelated-id", "name": "some-unrelated-token", "status": "active"}])
        self.assertIn("0 homelab-cloud-sync-r2-*/openbao-snapshot-* token(s)", printed)


if __name__ == "__main__":
    unittest.main()
