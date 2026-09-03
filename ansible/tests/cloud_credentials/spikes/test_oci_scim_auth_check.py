"""Unit tests for cloud_credentials.spikes.oci_scim_auth_check.

Run via `uv run pytest ansible/tests/ -v`. requests.get is mocked -
nothing here talks to a real tenancy.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from cloud_credentials.spikes import oci_scim_auth_check


class OciScimAuthCheckTests(unittest.TestCase):
    @patch.object(oci_scim_auth_check, "oci_rotation_auth_and_endpoint", return_value=(MagicMock(), "https://identity.example"))
    @patch.object(oci_scim_auth_check.requests, "get")
    def test_200_is_success(self, mock_get, mock_auth):
        mock_get.return_value = MagicMock(status_code=200, text="{}")
        rc = oci_scim_auth_check.main(["prog", "https://idcs-example.identity.oraclecloud.com"])
        self.assertEqual(rc, 0)
        # The classic identity.{region}... endpoint must never be the one
        # actually queried - that's the whole point of this spike.
        called_url = mock_get.call_args.args[0]
        self.assertIn("idcs-example", called_url)
        self.assertIn("/admin/v1/Schemas", called_url)

    @patch.object(oci_scim_auth_check, "oci_rotation_auth_and_endpoint", return_value=(MagicMock(), "https://identity.example"))
    @patch.object(oci_scim_auth_check.requests, "get")
    def test_401_is_a_confirmed_rejection_not_a_crash(self, mock_get, mock_auth):
        mock_get.return_value = MagicMock(status_code=401, text="unauthorized")
        rc = oci_scim_auth_check.main(["prog", "https://idcs-example.identity.oraclecloud.com"])
        self.assertEqual(rc, 1)

    def test_missing_domain_url_argument_is_a_usage_error(self):
        rc = oci_scim_auth_check.main(["prog"])
        self.assertEqual(rc, 2)

    @patch.object(oci_scim_auth_check, "oci_rotation_auth_and_endpoint", return_value=(MagicMock(), "https://identity.example"))
    @patch.object(oci_scim_auth_check.requests, "get")
    def test_trailing_slash_on_domain_url_does_not_double_up(self, mock_get, mock_auth):
        mock_get.return_value = MagicMock(status_code=200, text="{}")
        oci_scim_auth_check.main(["prog", "https://idcs-example.identity.oraclecloud.com/"])
        called_url = mock_get.call_args.args[0]
        self.assertNotIn("//admin", called_url)


if __name__ == "__main__":
    unittest.main()
