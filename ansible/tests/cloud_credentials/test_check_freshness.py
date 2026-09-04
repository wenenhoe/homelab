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
from cloud_credentials.expiry import URGENT_DAYS, WARNING_DAYS


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
    def _mock_scim_get_response(self, status_code: int, expires_on: str | None = None):
        resp = MagicMock(status_code=status_code, text=f"status {status_code}")
        resp.json.return_value = {"expiresOn": expires_on} if expires_on is not None else {}
        return resp

    @patch.object(check_freshness, "oci_scim_session")
    def test_fresh_stale_and_missing_all_reported(self, mock_scim_session):
        self.seed("oci-write-scim-id", "scim-write-1")
        self.seed("oci-read-scim-id", "scim-read-1")
        # rotation credential's -created-at deliberately not seeded

        session = MagicMock()
        fresh_expires_on = (datetime.now(UTC) + timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        stale_expires_on = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        session.get.side_effect = [
            self._mock_scim_get_response(200, fresh_expires_on),
            self._mock_scim_get_response(200, stale_expires_on),
        ]
        mock_scim_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        results = check_freshness.check_oci()

        statuses = {name: status for name, status, _ in results}
        self.assertEqual(statuses["oci write"], check_freshness.FRESH)
        self.assertEqual(statuses["oci read"], check_freshness.STALE)
        self.assertEqual(statuses["oci rotation credential"], check_freshness.CHECK_FAILED)

    @patch.object(check_freshness, "oci_scim_session")
    def test_missing_scim_id_is_a_check_failure_not_a_crash(self, mock_scim_session):
        # oci-write-scim-id deliberately not seeded — a leaf key created
        # before the SCIM migration (ADR 0016) would have no such file.
        session = MagicMock()
        mock_scim_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        results = check_freshness.check_oci()

        statuses = {name: status for name, status, _ in results}
        self.assertEqual(statuses["oci write"], check_freshness.CHECK_FAILED)
        session.get.assert_not_called()  # no scim_id, so no point calling out

    @patch.object(check_freshness, "oci_scim_session", side_effect=SystemExit(1))
    def test_auth_failure_fails_every_leaf_entry_but_not_the_rotation_credential_check(self, mock_scim_session):
        self.seed("_rotation-key-oci-created-at", datetime.now(UTC).isoformat())

        results = check_freshness.check_oci()

        statuses = {name: status for name, status, _ in results}
        self.assertEqual(statuses["oci write"], check_freshness.CHECK_FAILED)
        self.assertEqual(statuses["oci read"], check_freshness.CHECK_FAILED)
        # The rotation credential's own check is self-tracked and
        # doesn't depend on the SCIM session at all — an OAuth2 auth
        # failure for the leaf checks shouldn't also break this one.
        self.assertEqual(statuses["oci rotation credential"], check_freshness.FRESH)


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
            if url.endswith("/user/tokens/verify"):
                return MagicMock(json=lambda: {"success": True, "result": {"id": "x", "status": "active", "expires_on": future}})
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

    @patch.object(check_freshness.requests, "Session")
    def test_rotation_token_is_a_user_token_not_an_account_token(self, mock_session_cls):
        """Regression test for two wrong theories in a row before this
        one: the rotation token is a Cloudflare User API Token (My
        Profile > API Tokens), not an Account Owned one -
        /accounts/{account_id}/tokens/verify and List Tokens both only
        ever see the Account-owned category and would never find this
        token no matter how they're queried. /user/tokens/verify is the
        only endpoint that can actually check it, and needs no
        account_id to do so."""
        session = mock_session_cls.return_value

        def get(url):
            if url == "https://api.cloudflare.com/client/v4/user/tokens/verify":
                return MagicMock(json=lambda: {"success": True, "result": {"id": "x", "status": "active", "expires_on": "2099-01-01T00:00:00Z"}})
            raise AssertionError(f"check_r2 must not call the account-scoped tokens endpoints for the rotation token: {url}")

        session.get.side_effect = get

        result = check_freshness._r2_rotation_token_result(session)

        self.assertEqual(result[0], "r2 rotation token")
        self.assertEqual(result[1], check_freshness.FRESH)

    @patch.object(check_freshness.requests, "Session")
    def test_rotation_token_verify_failure_is_check_failed(self, mock_session_cls):
        session = mock_session_cls.return_value
        session.get.return_value = MagicMock(json=lambda: {"success": False, "errors": [{"code": 1000, "message": "Invalid API Token"}]})

        result = check_freshness._r2_rotation_token_result(session)

        self.assertEqual(result[1], check_freshness.CHECK_FAILED)

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

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")])
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.FRESH, "")])
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.CHECK_FAILED, "boom")])
    @patch.object(check_freshness.requests, "post")
    def test_uses_html_parse_mode_not_legacy_markdown(self, mock_post, mock_b2, mock_oci, mock_r2):
        """Regression test for two distinct incidents on legacy Markdown
        in a row, both confirmed live: an unescaped literal underscore
        in the static header broke every alert outright (400); after
        escaping it, Telegram's own documented rule ("escaping inside
        entities is not allowed") meant the escaped underscore inside
        the bold *...* span rendered as a literal visible backslash
        instead of being consumed. HTML mode has neither problem -
        confirmed here by checking the actual parse_mode and tag shape
        sent, not just that a message went out."""
        mock_post.return_value = MagicMock(raise_for_status=lambda: None)
        check_freshness.main()
        data = mock_post.call_args.kwargs["data"]
        self.assertEqual(data["parse_mode"], "HTML")
        self.assertIn("<b>cloud_credentials freshness check</b>", data["text"])
        self.assertNotIn("\\_", data["text"])  # no leftover Markdown-escape artifact

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")])
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.FRESH, "")])
    @patch.object(
        check_freshness,
        "check_b2",
        return_value=[("b2 write", check_freshness.CHECK_FAILED, "provider said <b>bad</b> & broken")],
    )
    @patch.object(check_freshness.requests, "post")
    def test_detail_containing_html_special_chars_is_escaped(self, mock_post, mock_b2, mock_oci, mock_r2):
        # Detail strings embed arbitrary provider error text and URLs -
        # unlike telegram_notify's other callers (all static templates),
        # this one will eventually interpolate a literal &, <, or > and
        # must not let it be interpreted as real markup.
        mock_post.return_value = MagicMock(raise_for_status=lambda: None)
        check_freshness.main()
        text = mock_post.call_args.kwargs["data"]["text"]
        self.assertIn("provider said &lt;b&gt;bad&lt;/b&gt; &amp; broken", text)
        self.assertNotIn("<b>bad</b>", text)


if __name__ == "__main__":
    unittest.main()
