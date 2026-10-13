"""Unit tests for cloud_credentials.verify.

Run via `uv run pytest tools/tests/ -v`. rclone is mocked at
subprocess.run; nothing here shells out to a real binary or talks to a
real provider.
"""

from __future__ import annotations

import configparser
import stat
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from cloud_credentials import verify


class TestVerifyMarkerKey:
    """Covers the fix for a real RetentionRuleViolation: a fixed, reused
    marker path broke permanently the moment the bucket had a retention
    rule, since the second write to the same key was a genuine
    overwrite-of-a-retained-object failure. Each verification must get
    its own key."""

    def test_two_calls_never_collide(self):
        keys = {verify._verify_marker_key("write") for _ in range(1000)}
        assert len(keys) == 1000

    def test_key_is_scoped_under_the_reserved_prefix_and_leaf(self):
        key = verify._verify_marker_key("write")
        assert key.startswith("_rotation-verify/write-")


class TestRunRcloneWithRetry:
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

    def _completed(self, returncode: int, stderr: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)

    @patch.object(verify.time, "sleep", autospec=True)
    @patch.object(verify.subprocess, "run", autospec=True)
    def test_retries_on_list_objects_propagation_error_then_succeeds(self, mock_run, mock_sleep):
        succeeded = self._completed(0)
        mock_run.side_effect = [
            self._completed(1, self.PROPAGATION_ERR_LIST),
            self._completed(1, self.PROPAGATION_ERR_LIST),
            succeeded,
        ]
        result = verify._run_rclone_with_retry(["rclone", "lsjson"], timeout=45)
        assert result is succeeded
        assert mock_run.call_count == 3
        assert mock_sleep.call_count == 2

    @patch.object(verify.time, "sleep", autospec=True)
    @patch.object(verify.subprocess, "run", autospec=True)
    def test_retries_on_head_object_propagation_error_then_succeeds(self, mock_run, mock_sleep):
        # The write leaf's failure shape — bare 403 Forbidden, no
        # SignatureDoesNotMatch text at all — is the specific case this
        # patch fixes; the previous two-marker gate never retried this.
        succeeded = self._completed(0)
        mock_run.side_effect = [
            self._completed(1, self.PROPAGATION_ERR_HEAD),
            succeeded,
        ]
        result = verify._run_rclone_with_retry(["rclone", "copyto"], timeout=45)
        assert result is succeeded
        assert mock_run.call_count == 2
        mock_sleep.assert_called_once()

    @patch.object(verify.time, "sleep", autospec=True)
    @patch.object(verify.subprocess, "run", autospec=True)
    def test_retries_on_r2_401_propagation_error_then_succeeds(self, mock_run, mock_sleep):
        # R2's version of the exact same underlying condition — a bare
        # 401 Unauthorized, no distinguishing text, different status
        # code from OCI's 403s. Confirmed live: 10s to resolve on a
        # throwaway measurement token.
        succeeded = self._completed(0)
        mock_run.side_effect = [
            self._completed(1, self.PROPAGATION_ERR_R2),
            succeeded,
        ]
        result = verify._run_rclone_with_retry(["rclone", "lsjson"], timeout=45)
        assert result is succeeded
        assert mock_run.call_count == 2
        mock_sleep.assert_called_once()

    @patch.object(verify.time, "sleep", autospec=True)
    @patch.object(verify.subprocess, "run", autospec=True)
    def test_does_not_retry_a_non_403_or_401_error(self, mock_run, mock_sleep):
        failed = self._completed(1, self.NON_RETRYABLE_ERR)
        mock_run.side_effect = [failed]
        result = verify._run_rclone_with_retry(["rclone", "lsjson"], timeout=45)
        assert result is failed
        mock_run.assert_called_once()
        mock_sleep.assert_not_called()

    @patch.object(verify.time, "sleep", autospec=True)
    @patch.object(verify.subprocess, "run", autospec=True)
    def test_timeout_expired_is_treated_as_non_retryable_failure(self, mock_run, mock_sleep):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["rclone", "lsjson"], timeout=45)
        result = verify._run_rclone_with_retry(["rclone", "lsjson"], timeout=45)
        assert result.returncode == 1
        mock_run.assert_called_once()
        mock_sleep.assert_not_called()

    @patch.object(verify.time, "sleep", autospec=True)
    @patch.object(verify.subprocess, "run", autospec=True)
    def test_gives_up_after_exhausting_retries(self, mock_run, mock_sleep):
        failed = self._completed(1, self.PROPAGATION_ERR_LIST)
        mock_run.return_value = failed
        result = verify._run_rclone_with_retry(["rclone", "lsjson"], timeout=45, retries=3, delay=1)
        assert result is failed
        assert mock_run.call_count == 3
        assert mock_sleep.call_count == 2  # sleeps between attempts, not after the last


class TestVerifyLeafViaRclone:
    """The gate that decides whether an old, working credential is revoked.

    The rclone config holds the key in plaintext and lives in a temporary
    directory the function deletes, so each test reads it from inside the
    stubbed rclone call, the only moment it exists.
    """

    ARGS = ("ACCESS", "SECRET", "https://s3.example.test", "region-1", "the-bucket")

    def _completed(self, returncode: int, stderr: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)

    @pytest.fixture
    def rclone_calls(self):
        """What each stubbed rclone call was given, read while its files still exist."""
        calls: list[dict] = []
        outcome = {"result": self._completed(0)}

        def run(cmd, timeout):
            conf_path = Path(cmd[cmd.index("--config") + 1])
            conf = configparser.ConfigParser()
            conf.read(conf_path)
            call = {
                "cmd": cmd,
                "timeout": timeout,
                "conf": dict(conf["verify"]),
                "conf_path": conf_path,
                "conf_mode": stat.S_IMODE(conf_path.stat().st_mode),
            }
            if "copyto" in cmd:
                call["uploaded_text"] = Path(cmd[cmd.index("copyto") + 1]).read_text()
            calls.append(call)
            return outcome["result"]

        with patch.object(verify, "_run_rclone_with_retry", autospec=True, side_effect=run):
            yield calls, outcome

    def test_read_leaf_lists_the_bucket_through_a_config_built_from_its_arguments(self, rclone_calls):
        calls, _ = rclone_calls

        ok, detail = verify.verify_leaf_via_rclone(*self.ARGS, "read")

        assert (ok, detail) == (True, "ListObjects succeeded")
        (call,) = calls
        assert call["cmd"][call["cmd"].index("lsjson") :] == ["lsjson", "verify:the-bucket", "--max-depth", "1"]
        assert call["conf"] == {
            "type": "s3",
            "provider": "Other",
            "access_key_id": "ACCESS",
            "secret_access_key": "SECRET",
            "endpoint": "https://s3.example.test",
            "region": "region-1",
            "force_path_style": "true",
            "no_check_bucket": "true",
        }

    def test_write_leaf_uploads_a_fresh_marker_under_the_reserved_prefix(self, rclone_calls):
        calls, _ = rclone_calls

        ok, detail = verify.verify_leaf_via_rclone(*self.ARGS, "write")

        assert (ok, detail) == (True, "PutObject succeeded")
        (call,) = calls
        destination = call["cmd"][-1]
        assert destination.startswith("verify:the-bucket/_rotation-verify/write-")
        assert call["uploaded_text"] == "homelab rotation-verify marker for the write leaf\n"

    def test_the_config_holding_the_key_is_private_and_removed_afterwards(self, rclone_calls):
        calls, _ = rclone_calls

        verify.verify_leaf_via_rclone(*self.ARGS, "read")

        (call,) = calls
        assert call["conf_mode"] == 0o600
        assert not call["conf_path"].exists()

    def test_the_timeout_reaches_both_rclone_and_the_retry_loop(self, rclone_calls):
        calls, _ = rclone_calls

        verify.verify_leaf_via_rclone(*self.ARGS, "read", timeout=7)

        (call,) = calls
        assert call["timeout"] == 7
        assert call["cmd"][call["cmd"].index("--timeout") + 1] == "7s"

    def test_a_failed_listing_is_reported_with_rclone_s_message(self, rclone_calls):
        _, outcome = rclone_calls
        outcome["result"] = self._completed(1, "  AccessDenied\n")

        ok, detail = verify.verify_leaf_via_rclone(*self.ARGS, "read")

        assert not ok
        assert detail == "rclone lsjson (ListObjects) failed: AccessDenied"

    def test_a_failed_upload_is_reported_with_rclone_s_message(self, rclone_calls):
        _, outcome = rclone_calls
        outcome["result"] = self._completed(1, "  Forbidden\n")

        ok, detail = verify.verify_leaf_via_rclone(*self.ARGS, "write")

        assert not ok
        assert detail == "rclone copyto (PutObject) failed: Forbidden"
