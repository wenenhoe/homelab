"""Unit tests for ansible/create_cloud_credentials.py's --rotate flow.

Same rationale/invocation as test_create_rotation_keys.py — see that
file's module docstring (run via `uv run pytest ansible/tests/ -v`).
rclone is mocked at subprocess.run; nothing here shells out to a real
binary or talks to a real provider.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import create_cloud_credentials as ccc  # noqa: E402


def _b2_create_key_response(access_key: str, secret_key: str) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"applicationKeyId": access_key, "applicationKey": secret_key}
    return resp


class VerifyMarkerKeyTests(unittest.TestCase):
    """Covers the fix for a real RetentionRuleViolation: a fixed, reused
    marker path broke permanently the moment the bucket had a retention
    rule, since the second write to the same key was a genuine
    overwrite-of-a-retained-object failure. Each verification must get
    its own key."""

    def test_two_calls_never_collide(self):
        keys = {ccc._verify_marker_key("write") for _ in range(1000)}
        self.assertEqual(len(keys), 1000)

    def test_key_is_scoped_under_the_reserved_prefix_and_leg(self):
        key = ccc._verify_marker_key("write")
        self.assertTrue(key.startswith("_rotation-verify/write-"))


class RunRcloneWithRetryTests(unittest.TestCase):
    """Covers the fix for OCI's key-propagation window: a freshly created
    customer secret key isn't always immediately usable by Object
    Storage's S3-compat API (confirmed live — an already-propagated key
    with an identical request succeeds; a just-created one doesn't,
    until it does). Retry only on that specific error signature."""

    # The two error shapes actually observed live for this exact
    # propagation condition — different S3 operations, different
    # wording, but both a StatusCode: 403.
    PROPAGATION_ERR_LIST = (
        "operation error S3: ListObjects, https response error StatusCode: 403, "
        "api error SignatureDoesNotMatch: The secret key required to complete "
        "authentication could not be found."
    )
    PROPAGATION_ERR_HEAD = "operation error S3: HeadObject, https response error StatusCode: 403, api error Forbidden: Forbidden"
    # Not a 403 at all — must still fail fast regardless of how broadly
    # 403s are retried.
    NON_RETRYABLE_ERR = "operation error S3: PutObject, https response error StatusCode: 400, api error InvalidRequest: bad bucket name"

    def _completed(self, returncode: int, stderr: str = "") -> MagicMock:
        return MagicMock(returncode=returncode, stderr=stderr)

    @patch.object(ccc.time, "sleep")
    @patch.object(ccc.subprocess, "run")
    def test_retries_on_list_objects_propagation_error_then_succeeds(self, mock_run, mock_sleep):
        mock_run.side_effect = [
            self._completed(1, self.PROPAGATION_ERR_LIST),
            self._completed(1, self.PROPAGATION_ERR_LIST),
            self._completed(0),
        ]
        result = ccc._run_rclone_with_retry(["rclone", "lsjson"], timeout=45)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(mock_run.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch.object(ccc.time, "sleep")
    @patch.object(ccc.subprocess, "run")
    def test_retries_on_head_object_propagation_error_then_succeeds(self, mock_run, mock_sleep):
        # The write leg's failure shape — bare 403 Forbidden, no
        # SignatureDoesNotMatch text at all — is the specific case this
        # patch fixes; the previous two-marker gate never retried this.
        mock_run.side_effect = [
            self._completed(1, self.PROPAGATION_ERR_HEAD),
            self._completed(0),
        ]
        result = ccc._run_rclone_with_retry(["rclone", "copyto"], timeout=45)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once()

    @patch.object(ccc.time, "sleep")
    @patch.object(ccc.subprocess, "run")
    def test_does_not_retry_a_non_403_error(self, mock_run, mock_sleep):
        mock_run.side_effect = [self._completed(1, self.NON_RETRYABLE_ERR)]
        result = ccc._run_rclone_with_retry(["rclone", "lsjson"], timeout=45)
        self.assertEqual(result.returncode, 1)
        mock_run.assert_called_once()
        mock_sleep.assert_not_called()

    @patch.object(ccc.time, "sleep")
    @patch.object(ccc.subprocess, "run")
    def test_gives_up_after_exhausting_retries(self, mock_run, mock_sleep):
        mock_run.return_value = self._completed(1, self.PROPAGATION_ERR_LIST)
        result = ccc._run_rclone_with_retry(["rclone", "lsjson"], timeout=45, retries=3, delay=1)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(mock_run.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)  # sleeps between attempts, not after the last


class RotationTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(ccc, "SECRETS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed(self, name: str, value: str) -> None:
        ccc.write_cache(name, value)


class B2RotationTests(RotationTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-backblaze-b2-key-id", "rot-id")
        self.seed("_rotation-key-backblaze-b2-application-key", "rot-key")
        self.seed("backblaze-b2-region", "us-west-004")
        self.seed("backblaze-b2-write-access-key", "OLD_ACCESS")
        self.seed("backblaze-b2-write-secret-key", "OLD_SECRET")

    @patch.object(ccc, "verify_leg_via_rclone", return_value=(True, "ok"))
    @patch.object(ccc.requests, "Session")
    def test_successful_rotation_revokes_old_key_and_caches_new_one(self, mock_session_cls, mock_verify):
        session = mock_session_cls.return_value
        session.post.side_effect = [
            MagicMock(raise_for_status=lambda: None, json=lambda: {"accountId": "acct", "apiUrl": "https://api"}),  # authorize done in b2_authorize
        ]
        # b2_authorize uses requests.get directly, not session — patch separately below.
        with patch.object(ccc.requests, "get") as mock_get:
            mock_get.return_value = MagicMock(raise_for_status=lambda: None, json=lambda: {"accountId": "acct", "apiUrl": "https://api", "authorizationToken": "tok"})
            session.post.side_effect = [
                MagicMock(raise_for_status=lambda: None, json=lambda: {"buckets": [{"bucketId": "bkt"}]}),  # bucket lookup
                _b2_create_key_response("NEW_ACCESS", "NEW_SECRET"),  # new key
                MagicMock(raise_for_status=lambda: None),  # delete old key
            ]
            ok = ccc.rotate_b2(["write"])

        self.assertTrue(ok)
        # Region matters, not just endpoint: a missing/wrong region is
        # exactly the live bug this caught (OCI 403 SignatureDoesNotMatch
        # outside the tenancy's home region) — assert the actual call
        # arguments, not just that verify ran.
        mock_verify.assert_called_once_with("NEW_ACCESS", "NEW_SECRET", "https://s3.us-west-004.backblazeb2.com", "us-west-004", ccc.B2_BUCKET, "write")
        # The old key's delete call must happen, and only after verify passed.
        delete_call = session.post.call_args_list[2]
        self.assertIn("b2_delete_key", delete_call.args[0])
        self.assertEqual(delete_call.kwargs["json"]["applicationKeyId"], "OLD_ACCESS")
        self.assertEqual((self.tmp / "backblaze-b2-write-access-key").read_text(), "NEW_ACCESS")
        self.assertEqual((self.tmp / "backblaze-b2-write-secret-key").read_text(), "NEW_SECRET")

    @patch.object(ccc, "verify_leg_via_rclone", return_value=(False, "auth failed"))
    @patch.object(ccc.requests, "Session")
    def test_failed_verification_leaves_old_key_untouched(self, mock_session_cls, mock_verify):
        session = mock_session_cls.return_value
        with patch.object(ccc.requests, "get") as mock_get:
            mock_get.return_value = MagicMock(raise_for_status=lambda: None, json=lambda: {"accountId": "acct", "apiUrl": "https://api", "authorizationToken": "tok"})
            session.post.side_effect = [
                MagicMock(raise_for_status=lambda: None, json=lambda: {"buckets": [{"bucketId": "bkt"}]}),  # bucket lookup
                _b2_create_key_response("NEW_ACCESS", "NEW_SECRET"),  # new key created
            ]
            ok = ccc.rotate_b2(["write"])

        self.assertFalse(ok)
        # No delete call: only 2 session.post calls happened (bucket lookup + create).
        self.assertEqual(session.post.call_count, 2)
        # Cache must be untouched — the old, still-valid key stays authoritative.
        self.assertEqual((self.tmp / "backblaze-b2-write-access-key").read_text(), "OLD_ACCESS")
        self.assertEqual((self.tmp / "backblaze-b2-write-secret-key").read_text(), "OLD_SECRET")


class OciRotationTests(RotationTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-oci-user-ocid", "ocid1.user.oc1..rot")
        self.seed("_rotation-key-oci-fingerprint", "aa:bb")
        self.seed("_rotation-key-oci-tenancy-ocid", "ocid1.tenancy.oc1..t")
        self.seed("_rotation-key-oci-region", "us-ashburn-1")
        (self.tmp / "_rotation-key-oci-private-key.pem").write_text("-----BEGIN-----")
        self.seed("_oci-leg-user-ocid-read", "ocid1.user.oc1..readleg")
        self.seed("oci-namespace", "mynamespace")
        self.seed("oci-region", "us-ashburn-1")
        self.seed("oci-read-access-key", "OLD_OCID")
        self.seed("oci-read-secret-key", "OLD_SECRET")

    @patch.object(ccc, "verify_leg_via_rclone", return_value=(True, "ok"))
    @patch.object(ccc, "OCISigner")
    @patch.object(ccc.requests, "Session")
    def test_successful_rotation_deletes_old_secret_key(self, mock_session_cls, mock_signer, mock_verify):
        session = mock_session_cls.return_value
        session.post.return_value = MagicMock(raise_for_status=lambda: None, json=lambda: {"id": "NEW_OCID", "key": "NEW_SECRET"})
        session.delete.return_value = MagicMock(raise_for_status=lambda: None)

        ok = ccc.rotate_oci(["read"])

        self.assertTrue(ok)
        mock_verify.assert_called_once_with(
            "NEW_OCID", "NEW_SECRET", "https://mynamespace.compat.objectstorage.us-ashburn-1.oraclecloud.com",
            "us-ashburn-1", ccc.OCI_BUCKET, "read",
        )
        session.delete.assert_called_once()
        self.assertIn("OLD_OCID", session.delete.call_args.args[0])
        self.assertEqual((self.tmp / "oci-read-access-key").read_text(), "NEW_OCID")
        self.assertEqual((self.tmp / "oci-read-secret-key").read_text(), "NEW_SECRET")

    @patch.object(ccc, "verify_leg_via_rclone", return_value=(False, "permission denied"))
    @patch.object(ccc, "OCISigner")
    @patch.object(ccc.requests, "Session")
    def test_failed_verification_never_calls_delete(self, mock_session_cls, mock_signer, mock_verify):
        session = mock_session_cls.return_value
        session.post.return_value = MagicMock(raise_for_status=lambda: None, json=lambda: {"id": "NEW_OCID", "key": "NEW_SECRET"})

        ok = ccc.rotate_oci(["read"])

        self.assertFalse(ok)
        session.delete.assert_not_called()
        self.assertEqual((self.tmp / "oci-read-access-key").read_text(), "OLD_OCID")


if __name__ == "__main__":
    unittest.main()
