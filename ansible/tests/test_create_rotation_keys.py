"""Unit tests for ansible/create_rotation_keys.py.

No pytest/molecule infra covers this file today (checked: neither script
appears in any CI workflow, pyproject.toml's dev group, or
docs/molecule-testing.md — Molecule's per-host model doesn't apply to a
plain controller-side script anyway). Written as stdlib
unittest.TestCase + unittest.mock (pytest collects and runs these with
no code changes needed), run via:

    uv run pytest ansible/tests/ -v

Every OCI HTTP call is mocked; nothing here talks to a real tenancy.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import create_rotation_keys as crk  # noqa: E402


class OciPolicyRecheckTests(unittest.TestCase):
    """Covers the fix for docs/cloud-credential-creation.md's former
    'Known gap': policy verification must run even when the rotation
    keypair is already cached, without regenerating that keypair."""

    def setUp(self):
        self.tmp = self._make_tmp_secrets_dir()
        patcher = patch.object(crk, "SECRETS_DIR", self.tmp)
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
            crk.write_cache(name, value)

    @patch.object(crk, "oci_master_auth_and_endpoint")
    @patch.object(crk, "oci_ensure_leaf_identity")
    @patch.object(crk, "oci_ensure_rotation_identity")
    def test_policy_recheck_runs_when_keypair_already_cached(
        self, mock_ensure_rotation, mock_ensure_leaf, mock_auth
    ):
        self._cache_full_keypair()
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_ensure_rotation.return_value = "ocid1.user.oc1..existing"

        crk.create_oci_rotation_key(admin_email="you@example.com")

        # The whole point of the fix: leaf + rotation policy checks fire
        # unconditionally, not gated behind the keypair cache.
        self.assertEqual(mock_ensure_leaf.call_count, 2)
        mock_ensure_rotation.assert_called_once()

    @patch.object(crk, "oci_master_auth_and_endpoint")
    @patch.object(crk, "oci_ensure_leaf_identity")
    @patch.object(crk, "oci_ensure_rotation_identity")
    @patch("cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key")
    def test_keypair_not_regenerated_when_cached(
        self, mock_genkey, mock_ensure_rotation, mock_ensure_leaf, mock_auth
    ):
        self._cache_full_keypair()
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_ensure_rotation.return_value = "ocid1.user.oc1..existing"

        crk.create_oci_rotation_key(admin_email="you@example.com")

        mock_genkey.assert_not_called()

    @patch.object(crk, "oci_master_auth_and_endpoint")
    @patch.object(crk, "oci_ensure_leaf_identity")
    @patch.object(crk, "oci_ensure_rotation_identity")
    def test_user_ocid_mismatch_is_a_hard_stop(self, mock_ensure_rotation, mock_ensure_leaf, mock_auth):
        # If 'homelab-key-rotation' now resolves to a different user than
        # the cached keypair was issued for, that keypair can't
        # authenticate as it — this must fail loudly, not silently
        # proceed with a mismatched identity.
        self._cache_full_keypair(user_ocid="ocid1.user.oc1..old")
        mock_auth.return_value = (MagicMock(), "https://identity.example", "ocid1.tenancy.oc1..t", "us-ashburn-1")
        mock_ensure_rotation.return_value = "ocid1.user.oc1..different"

        with self.assertRaises(SystemExit):
            crk.create_oci_rotation_key(admin_email="you@example.com")

    @patch.object(crk, "oci_master_auth_and_endpoint")
    @patch.object(crk, "oci_ensure_leaf_identity")
    @patch.object(crk, "oci_ensure_rotation_identity")
    @patch("cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key")
    def test_keypair_generated_and_cached_on_first_run(
        self, mock_genkey, mock_ensure_rotation, mock_ensure_leaf, mock_auth
    ):
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
            crk.create_oci_rotation_key(admin_email="you@example.com")

        mock_genkey.assert_called_once()
        self.assertTrue((self.tmp / "_rotation-key-oci-user-ocid").exists())
        self.assertEqual((self.tmp / "_rotation-key-oci-user-ocid").read_text(), "ocid1.user.oc1..new")


if __name__ == "__main__":
    unittest.main()
