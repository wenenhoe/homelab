"""Unit tests for cloud_credentials.check_freshness.

Run via `uv run pytest ansible/tests/ -v`. Every provider HTTP call is
mocked — this only exercises the fresh/stale/check-failed triage logic,
not real B2/OCI/Cloudflare behavior.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials import cache, check_freshness
from cloud_credentials.expiry import QUARTERLY_DAYS, URGENT_DAYS, WARNING_DAYS


class FreshnessTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(cache, "SECRETS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed(self, name: str, value: str) -> None:
        cache.write_cache(name, value)


class CheckB2Tests(FreshnessTestBase):
    @patch.object(check_freshness, "b2_list_keys")
    @patch.object(check_freshness, "b2_rotation_session", return_value=(MagicMock(), "acct", "https://api"))
    def test_fresh_and_stale_and_missing_keys_all_reported(self, mock_session, mock_list_keys):
        future_ms = (datetime.now(UTC) + timedelta(days=45)).timestamp() * 1000
        past_ms = (datetime.now(UTC) - timedelta(days=1)).timestamp() * 1000
        mock_list_keys.return_value = [
            {"keyName": "homelab-cloud-sync-write", "expirationTimestamp": future_ms},
            {"keyName": "homelab-cloud-sync-read", "expirationTimestamp": past_ms},
            # rotation key deliberately absent from the response
        ]

        results = check_freshness.check_b2()

        statuses = {name: status for name, status, _ in results}
        self.assertEqual(statuses["b2 write"], check_freshness.FRESH)
        self.assertEqual(statuses["b2 read"], check_freshness.STALE)
        self.assertEqual(statuses["b2 rotation key"], check_freshness.CHECK_FAILED)

    @patch.object(check_freshness, "b2_rotation_session", side_effect=SystemExit(1))
    def test_auth_failure_reports_check_failed_for_all_three(self, mock_session):
        results = check_freshness.check_b2()
        self.assertTrue(all(status == check_freshness.CHECK_FAILED for _, status, _ in results))
        self.assertEqual(len(results), 3)

    @patch.object(check_freshness, "b2_list_keys")
    @patch.object(check_freshness, "b2_rotation_session", return_value=(MagicMock(), "acct", "https://api"))
    def test_within_warning_window_is_expiring_soon_not_fresh_or_stale(self, mock_session, mock_list_keys):
        # This is the whole point of WARNING_DAYS: B2 enforces its own
        # expiry server-side, so this key still authenticates today,
        # but a plain fresh/stale split would say nothing until it's
        # already broken cloud_sync's next run.
        soon_ms = (datetime.now(UTC) + timedelta(days=WARNING_DAYS - 1)).timestamp() * 1000
        mock_list_keys.return_value = [{"keyName": "homelab-cloud-sync-write", "expirationTimestamp": soon_ms}]
        results = check_freshness.check_b2()
        statuses = {name: status for name, status, _ in results}
        self.assertEqual(statuses["b2 write"], check_freshness.WARNING)

    @patch.object(check_freshness, "b2_list_keys")
    @patch.object(check_freshness, "b2_rotation_session", return_value=(MagicMock(), "acct", "https://api"))
    def test_within_urgent_window_escalates_past_plain_warning(self, mock_session, mock_list_keys):
        # The whole point of a second tier: 10 days out is a different
        # conversation than 25 days out, even though both are technically
        # "not fresh". A single WARNING would flatten that distinction.
        soon_ms = (datetime.now(UTC) + timedelta(days=URGENT_DAYS - 1)).timestamp() * 1000
        mock_list_keys.return_value = [{"keyName": "homelab-cloud-sync-write", "expirationTimestamp": soon_ms}]
        results = check_freshness.check_b2()
        statuses = {name: status for name, status, _ in results}
        self.assertEqual(statuses["b2 write"], check_freshness.URGENT)


class CheckOciTests(FreshnessTestBase):
    def test_fresh_stale_and_missing_all_reported(self):
        self.seed("oci-write-created-at", datetime.now(UTC).isoformat())
        self.seed("oci-read-created-at", (datetime.now(UTC) - timedelta(days=QUARTERLY_DAYS + 1)).isoformat())
        # rotation keypair's -created-at deliberately not seeded

        results = check_freshness.check_oci()

        statuses = {name: status for name, status, _ in results}
        self.assertEqual(statuses["oci write"], check_freshness.FRESH)
        self.assertEqual(statuses["oci read"], check_freshness.STALE)
        self.assertEqual(statuses["oci rotation keypair"], check_freshness.CHECK_FAILED)


class CheckR2Tests(FreshnessTestBase):
    def setUp(self):
        super().setUp()
        self.seed("_rotation-key-cloudflare-r2-token", "admin-token")
        self.seed("cloudflare-r2-account-id", "acct123")
        self.seed("cloudflare-r2-write-access-key", "TOKEN_ID_WRITE")
        self.seed("cloudflare-r2-read-access-key", "TOKEN_ID_READ")

    @patch.object(check_freshness.requests, "Session")
    def test_fresh_and_stale_and_rotation_token_all_reported(self, mock_session_cls):
        session = mock_session_cls.return_value
        future = (datetime.now(UTC) + timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        past = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        def get(url):
            if url.endswith("/tokens/verify"):
                return MagicMock(json=lambda: {"success": True, "result": {"expires_on": future}})
            if "TOKEN_ID_WRITE" in url:
                return MagicMock(json=lambda: {"success": True, "result": {"expires_on": future}})
            if "TOKEN_ID_READ" in url:
                return MagicMock(json=lambda: {"success": True, "result": {"expires_on": past}})
            raise AssertionError(f"unexpected URL: {url}")

        session.get.side_effect = get

        results = check_freshness.check_r2()

        statuses = {name: status for name, status, _ in results}
        self.assertEqual(statuses["r2 write"], check_freshness.FRESH)
        self.assertEqual(statuses["r2 read"], check_freshness.STALE)
        self.assertEqual(statuses["r2 rotation token"], check_freshness.FRESH)

    def test_missing_rotation_token_never_prompts_and_reports_check_failed(self):
        # Overwrite setUp's seeded token — this test wants the "nothing
        # cached" path, not the happy path.
        (self.tmp / "_rotation-key-cloudflare-r2-token").unlink()

        with patch("getpass.getpass") as mock_prompt:
            results = check_freshness.check_r2()

        mock_prompt.assert_not_called()
        self.assertTrue(all(status == check_freshness.CHECK_FAILED for _, status, _ in results))


class MainExitCodeTests(FreshnessTestBase):
    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")])
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.STALE, "old")])
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.FRESH, "")])
    def test_stale_alone_does_not_fail_the_run(self, mock_b2, mock_oci, mock_r2):
        # Matches backup_agent's check-freshness.sh: ordinary expiry is
        # an alert to read in the journal, not a run failure — only an
        # actual check error should make the unit itself fail.
        self.assertEqual(check_freshness.main(), 0)

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")])
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.FRESH, "")])
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.CHECK_FAILED, "boom")])
    def test_check_failure_fails_the_run(self, mock_b2, mock_oci, mock_r2):
        self.assertEqual(check_freshness.main(), 1)


class TelegramAlertTests(FreshnessTestBase):
    def setUp(self):
        super().setUp()
        self.seed("telegram-token", "123:abc")
        self.seed("telegram-chat-id", "-100999")

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")])
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.FRESH, "")])
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.FRESH, "")])
    @patch.object(check_freshness.requests, "post")
    def test_all_fresh_sends_no_telegram_message(self, mock_post, mock_b2, mock_oci, mock_r2):
        # The whole point of alerting only on non-fresh outcomes: a
        # healthy weekly run shouldn't page anyone.
        check_freshness.main()
        mock_post.assert_not_called()

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")])
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.WARNING, "expires in 5d")])
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.FRESH, "")])
    @patch.object(check_freshness.requests, "post")
    def test_warning_alone_still_sends_a_telegram_alert(self, mock_post, mock_b2, mock_oci, mock_r2):
        # This is the actual point of adding WARNING — a checked-fine
        # "past its window" result used to not even alert; a "expiring
        # soon" result must, since it's the only outcome that gives any
        # lead time before B2/R2 actually reject the credential.
        self.seed("telegram-topic-id-backups", "42")
        mock_post.return_value = MagicMock(raise_for_status=lambda: None)

        check_freshness.main()

        mock_post.assert_called_once()
        url, kwargs = mock_post.call_args.args[0], mock_post.call_args.kwargs
        self.assertIn("bot123:abc/sendMessage", url)
        self.assertEqual(kwargs["data"]["chat_id"], "-100999")
        self.assertEqual(kwargs["data"]["message_thread_id"], "42")
        self.assertIn("oci write", kwargs["data"]["text"])

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")])
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.STALE, "old")])
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.FRESH, "")])
    @patch.object(check_freshness.requests, "post")
    def test_no_topic_id_cached_omits_the_param_instead_of_sending_empty(self, mock_post, mock_b2, mock_oci, mock_r2):
        # Telegram's API rejects message_thread_id outright if it's
        # passed empty rather than ignoring it (see
        # docs/telegram-notifications.md) - must be omitted, not "".
        mock_post.return_value = MagicMock(raise_for_status=lambda: None)
        check_freshness.main()
        self.assertNotIn("message_thread_id", mock_post.call_args.kwargs["data"])

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")])
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.STALE, "old")])
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.FRESH, "")])
    @patch.object(check_freshness.requests, "post")
    def test_missing_telegram_credentials_does_not_crash_the_run(self, mock_post, mock_b2, mock_oci, mock_r2):
        (self.tmp / "telegram-token").unlink()
        rc = check_freshness.main()
        mock_post.assert_not_called()
        self.assertEqual(rc, 0)  # STALE alone still doesn't fail the run, even unalerted


if __name__ == "__main__":
    unittest.main()
