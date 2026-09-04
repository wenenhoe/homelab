"""Unit tests for cloud_credentials.rotation_keys.oci_bootstrap.

Run via `uv run pytest ansible/tests/ -v`. Every OCI HTTP call is
mocked; nothing here talks to a real tenancy.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from cloud_credentials import cache
from cloud_credentials.rotation_keys import oci_bootstrap


class OciPolicyRecheckTests(unittest.TestCase):
    """Covers the fix for docs/cloud-credential-creation.md's former
    'Known gap': policy verification must run even when the rotation
    keypair is already cached, without regenerating that keypair."""

    def setUp(self):
        self.tmp = self._make_tmp_secrets_dir()
        patcher = patch.object(cache, "SECRETS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_tmp_secrets_dir(self) -> Path:
        import tempfile

        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d

    def _cache_full_keypair(self, user_ocid="ocid1.user.oc1..existing"):
        for name, value in [
            ("_rotation-key-oci-user-ocid", user_ocid),
            ("_rotation-key-oci-fingerprint", "aa:bb"),
            ("_rotation-key-oci-private-key.pem", "-----BEGIN-----"),
            ("_rotation-key-oci-tenancy-ocid", "ocid1.tenancy.oc1..t"),
            ("_rotation-key-oci-region", "us-ashburn-1"),
        ]:
            cache.write_cache(name, value)

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_ensure_rotation_identity")
    def test_policy_recheck_runs_when_keypair_already_cached(self, mock_ensure_rotation, mock_ensure_leaf, mock_auth):
        self._cache_full_keypair()
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_ensure_rotation.return_value = "ocid1.user.oc1..existing"

        oci_bootstrap.create_oci_rotation_key(admin_email="you@example.com")

        # The whole point of the fix: leaf + rotation policy checks fire
        # unconditionally, not gated behind the keypair cache.
        self.assertEqual(mock_ensure_leaf.call_count, 2)
        mock_ensure_rotation.assert_called_once()

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_ensure_rotation_identity")
    @patch("cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key")
    def test_keypair_not_regenerated_when_cached(self, mock_genkey, mock_ensure_rotation, mock_ensure_leaf, mock_auth):
        self._cache_full_keypair()
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_ensure_rotation.return_value = "ocid1.user.oc1..existing"

        oci_bootstrap.create_oci_rotation_key(admin_email="you@example.com")

        mock_genkey.assert_not_called()

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_ensure_rotation_identity")
    def test_user_ocid_mismatch_is_a_hard_stop(self, mock_ensure_rotation, mock_ensure_leaf, mock_auth):
        # If 'homelab-key-rotation' now resolves to a different user than
        # the cached keypair was issued for, that keypair can't
        # authenticate as it — this must fail loudly, not silently
        # proceed with a mismatched identity.
        self._cache_full_keypair(user_ocid="ocid1.user.oc1..old")
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_ensure_rotation.return_value = "ocid1.user.oc1..different"

        with self.assertRaises(SystemExit):
            oci_bootstrap.create_oci_rotation_key(admin_email="you@example.com")

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_ensure_rotation_identity")
    @patch("cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key")
    def test_keypair_generated_and_cached_on_first_run(self, mock_genkey, mock_ensure_rotation, mock_ensure_leaf, mock_auth):
        # Nothing cached yet: full first-run path, including the API-key
        # upload — this is the pre-existing behavior and must survive
        # the refactor unchanged.
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_ensure_rotation.return_value = "ocid1.user.oc1..new"

        fake_key = MagicMock()
        fake_key.private_bytes.return_value = b"-----BEGIN PRIVATE-----"
        fake_key.public_key.return_value.public_bytes.return_value = b"-----BEGIN PUBLIC-----"
        mock_genkey.return_value = fake_key

        with patch("requests.Session.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"fingerprint": "aa:bb:cc"})
            oci_bootstrap.create_oci_rotation_key(admin_email="you@example.com")

        mock_genkey.assert_called_once()
        self.assertTrue((self.tmp / "_rotation-key-oci-user-ocid").exists())
        self.assertEqual((self.tmp / "_rotation-key-oci-user-ocid").read_text(), "ocid1.user.oc1..new")
        # Self-tracked expiry (see ADR 0015) — this keypair has no native
        # expiry field, so a fresh creation must record its own timestamp.
        self.assertTrue((self.tmp / "_rotation-key-oci-created-at").exists())

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_ensure_rotation_identity")
    def test_created_at_not_touched_when_keypair_already_cached(self, mock_ensure_rotation, mock_ensure_leaf, mock_auth):
        self._cache_full_keypair()
        cache.write_cache("_rotation-key-oci-created-at", "2020-01-01T00:00:00+00:00")
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_ensure_rotation.return_value = "ocid1.user.oc1..existing"

        oci_bootstrap.create_oci_rotation_key(admin_email="you@example.com")

        # A re-run that only re-verifies policy must not reset the
        # timestamp check_freshness.py alerts against — resetting it
        # every run would make the credential appear permanently fresh.
        self.assertEqual((self.tmp / "_rotation-key-oci-created-at").read_text(), "2020-01-01T00:00:00+00:00")

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_ensure_rotation_identity")
    @patch.object(oci_bootstrap, "_verify_rotation_key")
    @patch("cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key")
    def test_successful_rotate_revokes_old_key_and_caches_new(self, mock_genkey, mock_verify, mock_ensure_rotation, mock_ensure_leaf, mock_auth):
        self._cache_full_keypair()
        cache.write_cache("_rotation-key-oci-fingerprint", "old:fp")
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_ensure_leaf.return_value = "ocid1.user.oc1..write-leaf"
        mock_ensure_rotation.return_value = "ocid1.user.oc1..existing"
        mock_verify.return_value = (True, "")

        fake_key = MagicMock()
        fake_key.private_bytes.return_value = b"-----BEGIN PRIVATE-----"
        fake_key.public_key.return_value.public_bytes.return_value = b"-----BEGIN PUBLIC-----"
        mock_genkey.return_value = fake_key

        with patch("requests.Session.post") as mock_post, patch("requests.Session.delete") as mock_delete:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"fingerprint": "new:fp"})
            mock_delete.return_value = MagicMock(status_code=204, raise_for_status=lambda: None)
            ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        self.assertTrue(ok)
        mock_verify.assert_called_once()
        # Old key must actually be revoked — the whole point of rotating it.
        deleted_paths = [c.args[0] for c in mock_delete.call_args_list]
        self.assertTrue(any("old:fp" in p for p in deleted_paths))
        self.assertEqual((self.tmp / "_rotation-key-oci-fingerprint").read_text(), "new:fp")

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_ensure_rotation_identity")
    @patch.object(oci_bootstrap, "_verify_rotation_key")
    @patch("cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key")
    def test_failed_verification_leaves_old_key_cached_and_cleans_up_new_one(self, mock_genkey, mock_verify, mock_ensure_rotation, mock_ensure_leaf, mock_auth):
        self._cache_full_keypair()
        cache.write_cache("_rotation-key-oci-fingerprint", "old:fp")
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_ensure_leaf.return_value = "ocid1.user.oc1..write-leaf"
        mock_ensure_rotation.return_value = "ocid1.user.oc1..existing"
        mock_verify.return_value = (False, "401 unauthorized")

        fake_key = MagicMock()
        fake_key.private_bytes.return_value = b"-----BEGIN PRIVATE-----"
        fake_key.public_key.return_value.public_bytes.return_value = b"-----BEGIN PUBLIC-----"
        mock_genkey.return_value = fake_key

        with patch("requests.Session.post") as mock_post, patch("requests.Session.delete") as mock_delete:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"fingerprint": "new:fp"})
            mock_delete.return_value = MagicMock(status_code=204, raise_for_status=lambda: None)
            ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        self.assertFalse(ok)
        # The old, still-working key must survive a failed rotation untouched.
        self.assertEqual((self.tmp / "_rotation-key-oci-fingerprint").read_text(), "old:fp")
        # Best-effort cleanup of the unverified new key, not the old one.
        deleted_paths = [c.args[0] for c in mock_delete.call_args_list]
        self.assertTrue(any("new:fp" in p for p in deleted_paths))
        self.assertFalse(any("old:fp" in p for p in deleted_paths))

    @patch.object(oci_bootstrap, "oci_master_auth_and_endpoint")
    @patch.object(oci_bootstrap, "oci_ensure_leaf_identity")
    @patch.object(oci_bootstrap, "oci_ensure_rotation_identity")
    def test_rotate_user_ocid_mismatch_returns_false_not_sysexit(self, mock_ensure_rotation, mock_ensure_leaf, mock_auth):
        # Unlike create's hard sys.exit (a one-time bootstrap failure),
        # rotate must return a plain bool so create_rotation_keys.py's
        # --rotate can report it as an ordinary failed run, matching how
        # the leaf rotate_* functions already behave.
        self._cache_full_keypair(user_ocid="ocid1.user.oc1..old")
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_ensure_leaf.return_value = "ocid1.user.oc1..write-leaf"
        mock_ensure_rotation.return_value = "ocid1.user.oc1..different"

        ok = oci_bootstrap.rotate_oci_rotation_key(admin_email="you@example.com")

        self.assertFalse(ok)


class VerifyRotationKeyRetryTests(unittest.TestCase):
    """Covers _verify_rotation_key's retry loop specifically — the fix
    for a real live finding: a brand-new OCI API signing key 401'd for
    ~180s before OCI recognized it (see ADR 0015-era investigation).
    Every requests.Session call is mocked; time.sleep is patched out so
    these run instantly regardless of the retry count exercised."""

    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        # OCISigner validates the key content immediately in __init__
        # (tries to actually parse it) — a placeholder string like
        # "-----BEGIN-----" fails before the retry loop ever runs. A
        # real (throwaway) key is required even though its content is
        # otherwise irrelevant to what these tests exercise.
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()

    @patch("time.sleep")
    @patch("requests.Session.delete")
    @patch("requests.Session.post")
    def test_succeeds_immediately_with_no_retry_needed(self, mock_post, mock_delete, mock_sleep):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"id": "key-id"})
        mock_delete.return_value = MagicMock(raise_for_status=lambda: None)

        ok, detail = oci_bootstrap._verify_rotation_key("user-ocid", "fp", self.private_pem, "tenancy-ocid", "https://identity.example", "leaf-user-ocid")

        self.assertTrue(ok)
        self.assertEqual(detail, "")
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch("requests.Session.delete")
    @patch("requests.Session.post")
    def test_retries_on_401_then_succeeds(self, mock_post, mock_delete, mock_sleep):
        # This is the exact real-world sequence that motivated the fix:
        # a fresh key 401s a few times, then OCI catches up.
        mock_post.side_effect = [
            MagicMock(status_code=401, text="Unauthorized"),
            MagicMock(status_code=401, text="Unauthorized"),
            MagicMock(status_code=200, json=lambda: {"id": "key-id"}),
        ]
        mock_delete.return_value = MagicMock(raise_for_status=lambda: None)

        ok, detail = oci_bootstrap._verify_rotation_key(
            "user-ocid", "fp", self.private_pem, "tenancy-ocid", "https://identity.example", "leaf-user-ocid", retries=5, delay=1
        )

        self.assertTrue(ok)
        self.assertEqual(detail, "")
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("time.sleep")
    @patch("requests.Session.post")
    def test_retries_on_403_too_not_only_401(self, mock_post, mock_sleep):
        # Same broad-match-on-status reasoning as verify.py's leaf-key
        # retry: OCI doesn't distinguish "not propagated yet" from a
        # genuine policy denial in the response for either status.
        mock_post.side_effect = [
            MagicMock(status_code=403, text="Forbidden"),
            MagicMock(status_code=200, json=lambda: {"id": "key-id"}),
        ]
        with patch("requests.Session.delete", return_value=MagicMock(raise_for_status=lambda: None)):
            ok, _ = oci_bootstrap._verify_rotation_key(
                "user-ocid", "fp", self.private_pem, "tenancy-ocid", "https://identity.example", "leaf-user-ocid", retries=5, delay=1
            )
        self.assertTrue(ok)

    @patch("time.sleep")
    @patch("requests.Session.post")
    def test_exhausting_retries_returns_false_with_detail(self, mock_post, mock_sleep):
        mock_post.return_value = MagicMock(status_code=401, text="Unauthorized")

        ok, detail = oci_bootstrap._verify_rotation_key(
            "user-ocid", "fp", self.private_pem, "tenancy-ocid", "https://identity.example", "leaf-user-ocid", retries=3, delay=1
        )

        self.assertFalse(ok)
        self.assertIn("401", detail)
        self.assertEqual(mock_post.call_count, 3)
        # Retries in between attempts only, not after the last one.
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("time.sleep")
    @patch("requests.Session.post")
    def test_non_propagation_error_fails_fast_without_retrying(self, mock_post, mock_sleep):
        # A 400 (e.g. malformed request) is never going to resolve by
        # waiting - retrying it for 15 minutes would just be a slow
        # failure instead of a fast, accurate one.
        mock_post.return_value = MagicMock(status_code=400, text="Bad Request")

        ok, _ = oci_bootstrap._verify_rotation_key(
            "user-ocid", "fp", self.private_pem, "tenancy-ocid", "https://identity.example", "leaf-user-ocid", retries=5, delay=1
        )

        self.assertFalse(ok)
        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
