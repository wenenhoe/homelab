"""Unit tests for cloud_credentials.verify.

Run via `uv run pytest ansible/tests/ -v`. rclone is mocked at
subprocess.run; nothing here shells out to a real binary or talks to a
real provider.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials import verify


class VerifyMarkerKeyTests(unittest.TestCase):
    """Covers the fix for a real RetentionRuleViolation: a fixed, reused
    marker path broke permanently the moment the bucket had a retention
    rule, since the second write to the same key was a genuine
    overwrite-of-a-retained-object failure. Each verification must get
    its own key."""

    def test_two_calls_never_collide(self):
        keys = {verify._verify_marker_key("write") for _ in range(1000)}
        self.assertEqual(len(keys), 1000)

    def test_key_is_scoped_under_the_reserved_prefix_and_leaf(self):
        key = verify._verify_marker_key("write")
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
    PROPAGATION_ERR_R2 = "operation error S3: ListObjects, https response error StatusCode: 401, api error Unauthorized: Unauthorized"
    # Not a 403 or 401 at all — must still fail fast regardless of how
    # broadly those two are retried.
    NON_RETRYABLE_ERR = "operation error S3: PutObject, https response error StatusCode: 400, api error InvalidRequest: bad bucket name"

    def _completed(self, returncode: int, stderr: str = "") -> MagicMock:
        return MagicMock(returncode=returncode, stderr=stderr)

    @patch.object(verify.time, "sleep")
    @patch.object(verify.subprocess, "run")
    def test_retries_on_list_objects_propagation_error_then_succeeds(self, mock_run, mock_sleep):
        mock_run.side_effect = [
            self._completed(1, self.PROPAGATION_ERR_LIST),
            self._completed(1, self.PROPAGATION_ERR_LIST),
            self._completed(0),
        ]
        result = verify._run_rclone_with_retry(["rclone", "lsjson"], timeout=45)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(mock_run.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch.object(verify.time, "sleep")
    @patch.object(verify.subprocess, "run")
    def test_retries_on_head_object_propagation_error_then_succeeds(self, mock_run, mock_sleep):
        # The write leaf's failure shape — bare 403 Forbidden, no
        # SignatureDoesNotMatch text at all — is the specific case this
        # patch fixes; the previous two-marker gate never retried this.
        mock_run.side_effect = [
            self._completed(1, self.PROPAGATION_ERR_HEAD),
            self._completed(0),
        ]
        result = verify._run_rclone_with_retry(["rclone", "copyto"], timeout=45)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once()

    @patch.object(verify.time, "sleep")
    @patch.object(verify.subprocess, "run")
    def test_retries_on_r2_401_propagation_error_then_succeeds(self, mock_run, mock_sleep):
        # R2's version of the exact same underlying condition — a bare
        # 401 Unauthorized, no distinguishing text, different status
        # code from OCI's 403s. Confirmed live: 10s to resolve on a
        # throwaway measurement token.
        mock_run.side_effect = [
            self._completed(1, self.PROPAGATION_ERR_R2),
            self._completed(0),
        ]
        result = verify._run_rclone_with_retry(["rclone", "lsjson"], timeout=45)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once()

    @patch.object(verify.time, "sleep")
    @patch.object(verify.subprocess, "run")
    def test_does_not_retry_a_non_403_or_401_error(self, mock_run, mock_sleep):
        mock_run.side_effect = [self._completed(1, self.NON_RETRYABLE_ERR)]
        result = verify._run_rclone_with_retry(["rclone", "lsjson"], timeout=45)
        self.assertEqual(result.returncode, 1)
        mock_run.assert_called_once()
        mock_sleep.assert_not_called()

    @patch.object(verify.time, "sleep")
    @patch.object(verify.subprocess, "run")
    def test_gives_up_after_exhausting_retries(self, mock_run, mock_sleep):
        mock_run.return_value = self._completed(1, self.PROPAGATION_ERR_LIST)
        result = verify._run_rclone_with_retry(["rclone", "lsjson"], timeout=45, retries=3, delay=1)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(mock_run.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)  # sleeps between attempts, not after the last


if __name__ == "__main__":
    unittest.main()
