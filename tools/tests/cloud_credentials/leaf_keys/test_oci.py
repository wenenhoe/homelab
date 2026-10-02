"""Unit tests for cloud_credentials.leaf_keys.oci.

Run via `uv run pytest tools/tests/ -v`. Every OCI Identity Domains
call is mocked at oci_identity_domains_client() (leaf_keys.oci's own
import of it) - nothing here talks to a real tenancy, and nothing here
exercises the SDK's own bearer-token signer or config validation (see
rotation_keys/test_oci_scim.py for that seam).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from _oci_objects import customer_secret_key, response
from cloud_credentials.leaf_keys import oci


def _scim_key_response(scim_id="NEW_SCIM_ID", access_key="NEW_ACCESS", secret_key="NEW_SECRET"):  # noqa: S107 - test fixture, not a real credential
    return response(customer_secret_key(scim_id, access_key, secret_key))


class TestOciRotation:
    @pytest.fixture(autouse=True)
    def _seeded(self, vault):
        vault.seed("_rotation-key-oci-domain-url", "https://idcs-example.identity.oraclecloud.com", category="rotation")
        vault.seed("_rotation-key-oci-client-id", "client-123", category="rotation")
        vault.seed("_rotation-key-oci-client-secret", "shh", category="rotation")
        vault.seed("_oci-leaf-user-ocid-read", "ocid1.user.oc1..readleaf", category="rotation")
        vault.seed("_oci-leaf-user-ocid-write", "ocid1.user.oc1..writeleaf", category="rotation")
        vault.seed("oci-namespace", "mynamespace")
        vault.seed("oci-region", "us-ashburn-1")
        vault.seed("oci-read-access-key", "OLD_ACCESS")
        vault.seed("oci-read-secret-key", "OLD_SECRET")
        vault.seed("oci-read-scim-id", "OLD_SCIM_ID")

    @patch.object(oci, "verify_leaf_via_rclone", return_value=(True, "ok"))
    @patch.object(oci, "oci_identity_domains_client", autospec=True)
    def test_successful_rotation_deletes_old_secret_key(self, mock_client_factory, mock_verify, vault, identity_domains_client):
        client = mock_client_factory.return_value = identity_domains_client
        client.create_customer_secret_key.return_value = _scim_key_response()

        ok = oci.rotate_oci(["read"])

        assert ok
        mock_verify.assert_called_once_with(
            "NEW_ACCESS",
            "NEW_SECRET",
            "https://mynamespace.compat.objectstorage.us-ashburn-1.oraclecloud.com",
            "us-ashburn-1",
            oci.OCI_BUCKET,
            "read",
        )
        client.delete_customer_secret_key.assert_called_once_with(customer_secret_key_id="OLD_SCIM_ID")
        assert vault.get("oci-read-access-key") == "NEW_ACCESS"
        assert vault.get("oci-read-secret-key") == "NEW_SECRET"
        assert vault.get("oci-read-scim-id") == "NEW_SCIM_ID"
        # expiresOn is native now (see ADR 0016) - no self-tracked
        # -created-at cache file should exist for a SCIM-created key.
        assert vault.get("oci-read-created-at") is None

    @patch.object(oci, "verify_leaf_via_rclone", return_value=(False, "permission denied"))
    @patch.object(oci, "oci_identity_domains_client", autospec=True)
    def test_failed_verification_never_calls_delete(self, mock_client_factory, mock_verify, vault, identity_domains_client):
        client = mock_client_factory.return_value = identity_domains_client
        client.create_customer_secret_key.return_value = _scim_key_response()

        ok = oci.rotate_oci(["read"])

        assert not ok
        client.delete_customer_secret_key.assert_not_called()
        assert vault.get("oci-read-access-key") == "OLD_ACCESS"
        assert vault.get("oci-read-scim-id") == "OLD_SCIM_ID"

    @patch.object(oci, "verify_leaf_via_rclone", return_value=(True, "ok"))
    @patch.object(oci, "oci_identity_domains_client", autospec=True)
    def test_revoke_failure_is_reported_not_raised(self, mock_client_factory, mock_verify, vault, identity_domains_client):
        # ServiceError, not requests.HTTPError - the SDK's own error
        # type, since delete_customer_secret_key goes through
        # IdentityDomainsClient now (Stage 2).
        client = mock_client_factory.return_value = identity_domains_client
        client.create_customer_secret_key.return_value = _scim_key_response()
        client.delete_customer_secret_key.side_effect = oci.oci.exceptions.ServiceError(409, "Conflict", {}, "already deleted")

        ok = oci.rotate_oci(["read"])

        # The new key is still verified and cached even though revoking
        # the old one failed - same contract as every other provider's
        # rotate_* (verify-then-revoke, revoke failure is a warning).
        assert ok
        assert vault.get("oci-read-access-key") == "NEW_ACCESS"

    @patch.object(oci, "oci_identity_domains_client", autospec=True)
    def test_create_uses_user_ocid_field_not_value(self, mock_client_factory, identity_domains_client):
        client = mock_client_factory.return_value = identity_domains_client
        client.create_customer_secret_key.return_value = _scim_key_response()

        oci.create_oci()

        # Only "write" gets created here - "read" is already fully
        # cached (access-key, secret-key, and scim-id all present, per
        # setUp) so it's correctly skipped.
        create_calls = client.create_customer_secret_key.call_args_list
        assert len(create_calls) == 1
        sent_key = create_calls[0].kwargs["customer_secret_key"]
        assert sent_key.user.ocid == "ocid1.user.oc1..writeleaf"

    @patch.object(oci, "oci_identity_domains_client", autospec=True)
    def test_missing_scim_id_alone_is_not_treated_as_already_done(self, mock_client_factory, vault, identity_domains_client):
        """Regression test for a real incident: oci-{leaf}-access-key
        and -secret-key existed but -scim-id didn't (from a run that
        predates this cache key, or an interrupted write), and the old
        two-field check treated that leaf as permanently 'done' -
        silently never backfilling the missing scim-id, which then made
        openbao_utils/audit.py misreport the actually-in-use key as an
        ORPHAN, since it had nothing to compare it against."""
        vault.seed("oci-write-access-key", "STALE_ACCESS_NO_SCIM_ID")
        vault.seed("oci-write-secret-key", "STALE_SECRET_NO_SCIM_ID")
        # oci-write-scim-id deliberately not seeded.
        client = mock_client_factory.return_value = identity_domains_client
        client.create_customer_secret_key.return_value = _scim_key_response(
            scim_id="BACKFILLED_SCIM_ID",
            access_key="FRESH_ACCESS",
            secret_key="FRESH_SECRET",
        )

        oci.create_oci()

        # "write" was NOT treated as done - a fresh key was created and
        # all three fields are now fully cached together.
        assert vault.get("oci-write-access-key") == "FRESH_ACCESS"
        assert vault.get("oci-write-secret-key") == "FRESH_SECRET"
        assert vault.get("oci-write-scim-id") == "BACKFILLED_SCIM_ID"
