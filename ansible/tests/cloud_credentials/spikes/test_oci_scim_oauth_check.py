"""Unit tests for cloud_credentials.spikes.oci_scim_oauth_check.

Run via `uv run pytest ansible/tests/ -v`. requests and getpass are
mocked - nothing here talks to a real tenancy.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from cloud_credentials.spikes import oci_scim_oauth_check

ARGV = ["prog", "https://idcs-example.identity.oraclecloud.com", "client-id-123", "ocid1.user.oc1..leaf"]


def _mock_response(status_code: int, json_body: dict | None = None, text: str = ""):
    resp = MagicMock(status_code=status_code, text=text or str(json_body))
    resp.json.return_value = json_body or {}
    return resp


class OciScimOauthCheckTests(unittest.TestCase):
    def setUp(self):
        self.getpass_patch = patch.object(oci_scim_oauth_check.getpass, "getpass", return_value="shh")
        self.getpass_patch.start()
        self.addCleanup(self.getpass_patch.stop)

    def test_missing_arguments_is_a_usage_error(self):
        rc = oci_scim_oauth_check.main(["prog", "https://x"])
        self.assertEqual(rc, 2)

    @patch.object(oci_scim_oauth_check.requests, "post")
    def test_failed_token_exchange_stops_before_any_scim_call(self, mock_post):
        mock_post.return_value = _mock_response(401, text="invalid_client")
        rc = oci_scim_oauth_check.main(ARGV)
        self.assertEqual(rc, 1)
        mock_post.assert_called_once()  # only the token call, never a SCIM call

    @patch.object(oci_scim_oauth_check.requests.Session, "delete")
    @patch.object(oci_scim_oauth_check.requests.Session, "post")
    @patch.object(oci_scim_oauth_check.requests, "post")
    def test_full_round_trip_success(self, mock_token_post, mock_session_post, mock_session_delete):
        mock_token_post.return_value = _mock_response(200, {"access_token": "tok123"})
        expires_on = oci_scim_oauth_check.rfc3339_in(1)
        with patch.object(oci_scim_oauth_check, "rfc3339_in", return_value=expires_on):
            mock_session_post.return_value = _mock_response(201, {"id": "key-1", "expiresOn": expires_on})
            mock_session_delete.return_value = _mock_response(204)
            rc = oci_scim_oauth_check.main(ARGV)
        self.assertEqual(rc, 0)
        mock_session_delete.assert_called_once()
        deleted_url = mock_session_delete.call_args.args[0]
        self.assertIn("CustomerSecretKeys/key-1", deleted_url)
        # user.ocid, never user.value - value is a different, shorter
        # SCIM-internal id and 400s on an OCID (confirmed live). A
        # regression back to `value` here would reintroduce that bug.
        sent_body = mock_session_post.call_args.kwargs["json"]
        self.assertEqual(sent_body["user"], {"ocid": ARGV[3]})

    @patch.object(oci_scim_oauth_check.requests.Session, "post")
    @patch.object(oci_scim_oauth_check.requests, "post")
    def test_scim_create_failure_after_good_token_is_reported_distinctly(self, mock_token_post, mock_session_post):
        mock_token_post.return_value = _mock_response(200, {"access_token": "tok123"})
        mock_session_post.return_value = _mock_response(403, text="insufficient_scope")
        rc = oci_scim_oauth_check.main(ARGV)
        self.assertEqual(rc, 1)

    @patch.object(oci_scim_oauth_check.requests.Session, "delete")
    @patch.object(oci_scim_oauth_check.requests.Session, "post")
    @patch.object(oci_scim_oauth_check.requests, "post")
    def test_expires_on_genuine_mismatch_still_succeeds_but_is_flagged(self, mock_token_post, mock_session_post, mock_session_delete):
        """A genuinely different instant is surfaced, not hidden - but
        doesn't itself fail the run, since auth+create+delete all still
        worked; only cleanup failures and outright HTTP failures return
        non-zero."""
        mock_token_post.return_value = _mock_response(200, {"access_token": "tok123"})
        mock_session_post.return_value = _mock_response(201, {"id": "key-1", "expiresOn": "1970-01-01T00:00:00Z"})
        mock_session_delete.return_value = _mock_response(204)
        rc = oci_scim_oauth_check.main(ARGV)
        self.assertEqual(rc, 0)

    @patch.object(oci_scim_oauth_check.requests.Session, "delete")
    @patch.object(oci_scim_oauth_check.requests.Session, "post")
    @patch.object(oci_scim_oauth_check.requests, "post")
    def test_expires_on_millisecond_formatting_is_not_a_mismatch(self, mock_token_post, mock_session_post, mock_session_delete):
        """Confirmed live: OCI echoes expiresOn with explicit .000
        milliseconds even when the request sent none - same instant,
        different string. Must not be reported as a mismatch."""
        mock_token_post.return_value = _mock_response(200, {"access_token": "tok123"})
        sent = "2026-09-05T09:44:50Z"
        with patch.object(oci_scim_oauth_check, "rfc3339_in", return_value=sent):
            mock_session_post.return_value = _mock_response(201, {"id": "key-1", "expiresOn": "2026-09-05T09:44:50.000Z"})
            mock_session_delete.return_value = _mock_response(204)
            with patch("sys.stdout") as mock_stdout:
                rc = oci_scim_oauth_check.main(ARGV)
        self.assertEqual(rc, 0)
        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        self.assertIn("confirmed", printed)
        self.assertNotIn("MISMATCH", printed)

    @patch.object(oci_scim_oauth_check.requests.Session, "delete")
    @patch.object(oci_scim_oauth_check.requests.Session, "post")
    @patch.object(oci_scim_oauth_check.requests, "post")
    def test_key_material_present_is_reported_without_ever_printing_the_secret(self, mock_token_post, mock_session_post, mock_session_delete):
        mock_token_post.return_value = _mock_response(200, {"access_token": "tok123"})
        fake_secret = "totally-fake-secret-value-do-not-leak-me"  # noqa: S105 - test fixture, not a real credential
        mock_session_post.return_value = _mock_response(
            201, {"id": "key-1", "expiresOn": oci_scim_oauth_check.rfc3339_in(1), "accessKey": "fake-access-key", "secretKey": fake_secret}
        )
        mock_session_delete.return_value = _mock_response(204)
        with patch("sys.stdout") as mock_stdout, patch("sys.stderr") as mock_stderr:
            rc = oci_scim_oauth_check.main(ARGV)
        self.assertEqual(rc, 0)
        printed = "".join(call.args[0] for calls in (mock_stdout.write.call_args_list, mock_stderr.write.call_args_list) for call in calls if call.args)
        self.assertIn("Live key material returned", printed)
        self.assertNotIn(fake_secret, printed)  # the actual secret must never appear in output

    @patch.object(oci_scim_oauth_check.requests.Session, "delete")
    @patch.object(oci_scim_oauth_check.requests.Session, "post")
    @patch.object(oci_scim_oauth_check.requests, "post")
    def test_missing_key_material_is_reported_but_still_succeeds(self, mock_token_post, mock_session_post, mock_session_delete):
        """Absence of accessKey/secretKey answers ADR 0016's open question
        the other way (SCIM create is metadata-only here) but isn't
        itself a failure - auth, create, and delete all still worked."""
        mock_token_post.return_value = _mock_response(200, {"access_token": "tok123"})
        mock_session_post.return_value = _mock_response(201, {"id": "key-1", "expiresOn": oci_scim_oauth_check.rfc3339_in(1)})
        mock_session_delete.return_value = _mock_response(204)
        with patch("sys.stderr") as mock_stderr:
            rc = oci_scim_oauth_check.main(ARGV)
        self.assertEqual(rc, 0)
        printed_err = "".join(call.args[0] for call in mock_stderr.write.call_args_list if call.args)
        self.assertIn("NOT returned", printed_err)


if __name__ == "__main__":
    unittest.main()
