"""Unit tests for cloud_credentials.spikes.oci_scim_app_secret_check.

Run via `uv run pytest ansible/tests/ -v`. Every HTTP call and the
OAuth2 token exchange are mocked; nothing here talks to a real
tenancy or regenerates a real secret.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from cloud_credentials import cache
from cloud_credentials.spikes import oci_scim_app_secret_check as spike

ARGV = ["prog", "homelab-oci-scim-rotation"]


def _mock_response(status_code: int, json_body: dict | None = None, text: str = ""):
    resp = MagicMock(status_code=status_code, text=text or str(json_body))
    resp.json.return_value = json_body or {}
    return resp


class OciScimAppSecretCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(cache, "SECRETS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        cache.write_cache("_rotation-key-oci-domain-url", "https://idcs-example.identity.oraclecloud.com")
        cache.write_cache("_rotation-key-oci-client-id", "client-123")
        cache.write_cache("_rotation-key-oci-client-secret", "OLD_SECRET")

    def test_missing_arguments_is_a_usage_error(self):
        rc = spike.main(["prog"])
        self.assertEqual(rc, 2)

    @patch.object(spike, "oci_scim_session", side_effect=SystemExit(1))
    def test_old_secret_auth_failure_stops_immediately(self, mock_session):
        rc = spike.main(ARGV)
        self.assertEqual(rc, 1)
        self.assertFalse((self.tmp / "_rotation-key-oci-client-secret").read_text() != "OLD_SECRET")

    @patch.object(spike, "oci_scim_session")
    def test_app_search_failure_stops_before_regenerate(self, mock_session):
        session = MagicMock()
        session.get.return_value = _mock_response(403, text="insufficient_scope")
        mock_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        rc = spike.main(ARGV)

        self.assertEqual(rc, 1)
        session.post.assert_not_called()
        self.assertEqual(cache.read_cache("_rotation-key-oci-client-secret"), "OLD_SECRET")

    @patch.object(spike, "oci_scim_session")
    def test_app_not_found_stops_before_regenerate(self, mock_session):
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"Resources": []})
        mock_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        rc = spike.main(ARGV)

        self.assertEqual(rc, 1)
        session.post.assert_not_called()

    @patch.object(spike, "oci_scim_session")
    def test_regenerate_failure_leaves_old_secret_untouched(self, mock_session):
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"Resources": [{"id": "app-1"}]})
        session.post.return_value = _mock_response(403, text="insufficient_scope")
        mock_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        rc = spike.main(ARGV)

        self.assertEqual(rc, 1)
        self.assertEqual(cache.read_cache("_rotation-key-oci-client-secret"), "OLD_SECRET")
        self.assertIsNone(cache.read_cache("_rotation-key-oci-app-id"))

    @patch.object(spike, "oci_scim_session")
    def test_regenerate_success_without_secret_field_caches_nothing(self, mock_session):
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"Resources": [{"id": "app-1"}]})
        session.post.return_value = _mock_response(201, {"id": "regen-1"})  # no clientSecret
        mock_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        rc = spike.main(ARGV)

        self.assertEqual(rc, 1)
        self.assertEqual(cache.read_cache("_rotation-key-oci-client-secret"), "OLD_SECRET")

    @patch.object(spike, "oci_scim_access_token", side_effect=RuntimeError("network blip"))
    @patch.object(spike, "oci_scim_session")
    def test_verification_failure_still_caches_the_new_secret(self, mock_session, mock_verify_token):
        """The important safety property: a failed verification round-trip
        must not throw away the only copy of a secret OCI shows once -
        the old secret is already gone by this point regardless."""
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"Resources": [{"id": "app-1"}]})
        session.post.return_value = _mock_response(201, {"id": "regen-1", "clientSecret": "NEW_SECRET"})
        mock_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        rc = spike.main(ARGV)

        self.assertEqual(rc, 1)
        self.assertEqual(cache.read_cache("_rotation-key-oci-client-secret"), "NEW_SECRET")
        self.assertEqual(cache.read_cache("_rotation-key-oci-app-id"), "app-1")

    @patch.object(spike, "oci_scim_access_token", return_value="new-token")
    @patch.object(spike, "oci_scim_session")
    def test_full_success_caches_new_secret_and_never_prints_it(self, mock_session, mock_verify_token):
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"Resources": [{"id": "app-1"}]})
        session.post.return_value = _mock_response(201, {"id": "regen-1", "clientSecret": "NEW_SECRET"})
        mock_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        with patch("sys.stdout") as mock_stdout, patch("sys.stderr") as mock_stderr:
            rc = spike.main(ARGV)

        self.assertEqual(rc, 0)
        self.assertEqual(cache.read_cache("_rotation-key-oci-client-secret"), "NEW_SECRET")
        self.assertEqual(cache.read_cache("_rotation-key-oci-app-id"), "app-1")
        self.assertTrue(cache.read_cache("_rotation-key-oci-created-at"))
        printed = "".join(call.args[0] for calls in (mock_stdout.write.call_args_list, mock_stderr.write.call_args_list) for call in calls if call.args)
        self.assertNotIn("NEW_SECRET", printed)


if __name__ == "__main__":
    unittest.main()
