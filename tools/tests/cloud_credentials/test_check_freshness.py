"""Unit tests for cloud_credentials.check_freshness.

Run via `uv run pytest tools/tests/ -v`. Every provider HTTP call is
mocked — this only exercises the fresh/stale/check-failed triage logic,
not real B2/OCI/Cloudflare behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import call, patch

import oci.exceptions
import pytest
import requests
from _b2_objects import application_key, stubbed_b2_api
from _oci_objects import customer_secret_key
from _oci_objects import response as oci_response
from _responses import response
from cloud_credentials import check_freshness
from cloud_credentials.expiry import URGENT_DAYS, WARNING_DAYS


def seed_telegram(fake_vault, name: str, value: str) -> None:
    fake_vault.seed_path(f"{check_freshness._TELEGRAM_VAULT_SCOPE}/{name}", value)


def delete_telegram(fake_vault, name: str) -> None:
    fake_vault.store.pop(f"{check_freshness._TELEGRAM_VAULT_SCOPE}/{name}", None)


def has_a_timeout(call) -> bool:
    timeout = call.kwargs.get("timeout")
    return isinstance(timeout, int | float) and timeout > 0


def _b2_key(key_id: str, expiration_ms: float | None):
    return application_key(key_id, expiration_ms)


class TestClassify:
    """One hour of margin on each side of a boundary keeps these independent of the clock ticking between the test's `now` and the code's."""

    @pytest.mark.parametrize(
        ("until_expiry", "status", "detail"),
        [
            pytest.param(timedelta(hours=-1), check_freshness.STALE, "expired {at}", id="an-hour-past-expiry"),
            pytest.param(timedelta(hours=1), check_freshness.URGENT, "expires in 0d ({at})", id="an-hour-before-expiry"),
            pytest.param(timedelta(days=URGENT_DAYS, hours=1), check_freshness.URGENT, f"expires in {URGENT_DAYS}d ({{at}})", id="last-day-of-urgent"),
            pytest.param(
                timedelta(days=URGENT_DAYS + 1, hours=1), check_freshness.WARNING, f"expires in {URGENT_DAYS + 1}d ({{at}})", id="first-day-of-warning"
            ),
            pytest.param(timedelta(days=WARNING_DAYS, hours=1), check_freshness.WARNING, f"expires in {WARNING_DAYS}d ({{at}})", id="last-day-of-warning"),
            pytest.param(timedelta(days=WARNING_DAYS + 1, hours=1), check_freshness.FRESH, "", id="first-day-of-fresh"),
        ],
    )
    def test_status_and_detail_either_side_of_each_boundary(self, until_expiry, status, detail):
        expires_at = datetime.now(UTC) + until_expiry

        assert check_freshness._classify(expires_at) == (status, detail.format(at=expires_at.isoformat()))


@pytest.mark.usefixtures("fake_vault")
class TestCheckB2:
    @patch.object(check_freshness, "b2_list_keys", autospec=True)
    @patch.object(check_freshness, "b2_rotation_api", return_value=stubbed_b2_api(), autospec=True)
    def test_fresh_and_stale_and_missing_keys_all_reported(self, mock_api, mock_list_keys, vault):
        future_ms = (datetime.now(UTC) + timedelta(days=45)).timestamp() * 1000
        past_ms = (datetime.now(UTC) - timedelta(days=1)).timestamp() * 1000
        vault.seed("backblaze-b2-write-access-key", "key-write-1")
        vault.seed("backblaze-b2-read-access-key", "key-read-1")
        # rotation key id deliberately not seeded, mirroring the key
        # itself being "absent from the response" below
        mock_list_keys.return_value = [
            _b2_key("key-write-1", future_ms),
            _b2_key("key-read-1", past_ms),
            # rotation key deliberately absent from the response
        ]

        results = check_freshness.check_b2()

        statuses = {name: status for name, status, _ in results}
        assert statuses["b2 write"] == check_freshness.FRESH
        assert statuses["b2 read"] == check_freshness.STALE
        assert statuses["b2 rotation key"] == check_freshness.CHECK_FAILED

    @patch.object(check_freshness, "b2_rotation_api", side_effect=SystemExit(1), autospec=True)
    def test_auth_failure_reports_check_failed_for_all_three(self, mock_api):
        results = check_freshness.check_b2()
        assert all(status == check_freshness.CHECK_FAILED for _, status, _ in results)
        assert len(results) == 3

    @patch.object(check_freshness, "b2_list_keys", autospec=True)
    @patch.object(check_freshness, "b2_rotation_api", return_value=stubbed_b2_api(), autospec=True)
    def test_within_warning_window_is_expiring_soon_not_fresh_or_stale(self, mock_api, mock_list_keys, vault):
        # This is the whole point of WARNING_DAYS: B2 enforces its own
        # expiry server-side, so this key still authenticates today,
        # but a plain fresh/stale split would say nothing until it's
        # already broken cloud_sync's next run.
        soon_ms = (datetime.now(UTC) + timedelta(days=WARNING_DAYS - 1)).timestamp() * 1000
        vault.seed("backblaze-b2-write-access-key", "key-write-1")
        mock_list_keys.return_value = [_b2_key("key-write-1", soon_ms)]
        results = check_freshness.check_b2()
        statuses = {name: status for name, status, _ in results}
        assert statuses["b2 write"] == check_freshness.WARNING

    @patch.object(check_freshness, "b2_list_keys", autospec=True)
    @patch.object(check_freshness, "b2_rotation_api", return_value=stubbed_b2_api(), autospec=True)
    def test_within_urgent_window_escalates_past_plain_warning(self, mock_api, mock_list_keys, vault):
        # The whole point of a second tier: 10 days out is a different
        # conversation than 25 days out, even though both are technically
        # "not fresh". A single WARNING would flatten that distinction.
        soon_ms = (datetime.now(UTC) + timedelta(days=URGENT_DAYS - 1)).timestamp() * 1000
        vault.seed("backblaze-b2-write-access-key", "key-write-1")
        mock_list_keys.return_value = [_b2_key("key-write-1", soon_ms)]
        results = check_freshness.check_b2()
        statuses = {name: status for name, status, _ in results}
        assert statuses["b2 write"] == check_freshness.URGENT


def _secret_key_response(expires_on: str | None):
    return oci_response(customer_secret_key("scim-id", "ACCESS", "SECRET", expires_on=expires_on))


def _rfc3339_in(**delta) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.usefixtures("fake_vault")
class TestCheckOci:
    @pytest.fixture(autouse=True)
    def oci_client_factory(self, identity_domains_client):
        with patch.object(check_freshness, "oci_identity_domains_client", return_value=identity_domains_client, autospec=True) as factory:
            yield factory

    def test_fresh_stale_and_missing_all_reported(self, identity_domains_client, vault):
        vault.seed("oci-write-scim-id", "scim-write-1")
        vault.seed("oci-read-scim-id", "scim-read-1")
        # rotation credential's -created-at deliberately not seeded
        identity_domains_client.get_customer_secret_key.side_effect = [
            _secret_key_response(_rfc3339_in(days=45)),
            _secret_key_response(_rfc3339_in(days=-1)),
        ]

        results = check_freshness.check_oci()

        statuses = {name: status for name, status, _ in results}
        assert statuses["oci write"] == check_freshness.FRESH
        assert statuses["oci read"] == check_freshness.STALE
        assert statuses["oci rotation credential"] == check_freshness.CHECK_FAILED

    def test_each_leaf_is_fetched_by_its_stored_scim_id(self, identity_domains_client, vault):
        vault.seed("oci-write-scim-id", "scim-write-1")
        vault.seed("oci-read-scim-id", "scim-read-1")
        identity_domains_client.get_customer_secret_key.return_value = _secret_key_response("2099-01-01T00:00:00Z")

        check_freshness.check_oci()

        assert identity_domains_client.get_customer_secret_key.call_args_list == [call("scim-write-1"), call("scim-read-1")]

    def test_missing_scim_id_is_a_check_failure_not_a_crash(self, identity_domains_client):
        # oci-write-scim-id deliberately not seeded — a leaf key created
        # before the SCIM migration (ADR 0016) would have no such file.
        results = check_freshness.check_oci()

        statuses = {name: status for name, status, _ in results}
        assert statuses["oci write"] == check_freshness.CHECK_FAILED
        identity_domains_client.get_customer_secret_key.assert_not_called()  # no scim_id, so no point calling out

    def test_key_without_an_expiry_is_a_check_failure(self, identity_domains_client, vault):
        vault.seed("oci-write-scim-id", "scim-write-1")
        identity_domains_client.get_customer_secret_key.return_value = _secret_key_response(None)

        results = check_freshness.check_oci()

        assert next((status, detail) for name, status, detail in results if name == "oci write") == (
            check_freshness.CHECK_FAILED,
            "key has no expiresOn - created before the SCIM migration (ADR 0016)?",
        )

    @pytest.mark.parametrize(
        ("error", "detail"),
        [
            pytest.param(oci.exceptions.ServiceError(404, "NotAuthorizedOrNotFound", {}, "no such key"), "no such key", id="service-error"),
            pytest.param(oci.exceptions.ConnectTimeout(Exception("timed out")), "timed out", id="connect-timeout"),
            pytest.param(oci.exceptions.RequestException(Exception("connection reset")), "connection reset", id="transport-failure"),
        ],
    )
    def test_an_sdk_error_fails_that_leaf_and_names_the_cause_without_stopping_the_next(self, identity_domains_client, vault, error, detail):
        vault.seed("oci-write-scim-id", "scim-write-1")
        vault.seed("oci-read-scim-id", "scim-read-1")
        identity_domains_client.get_customer_secret_key.side_effect = [error, _secret_key_response("2099-01-01T00:00:00Z")]

        results = check_freshness.check_oci()

        by_name = {name: (status, text) for name, status, text in results}
        assert by_name["oci write"][0] == check_freshness.CHECK_FAILED
        assert "request failed: " in by_name["oci write"][1]
        assert detail in by_name["oci write"][1]
        assert by_name["oci read"] == (check_freshness.FRESH, "")

    def test_rotation_credential_age_is_reported_alongside_healthy_leaf_keys(self, identity_domains_client, vault):
        vault.seed("oci-write-scim-id", "scim-write-1")
        vault.seed("oci-read-scim-id", "scim-read-1")
        vault.seed("_rotation-key-oci-created-at", datetime.now(UTC).isoformat(), category="rotation")
        identity_domains_client.get_customer_secret_key.return_value = _secret_key_response(_rfc3339_in(days=45))

        results = check_freshness.check_oci()

        assert [(name, status) for name, status, _ in results] == [
            ("oci write", check_freshness.FRESH),
            ("oci read", check_freshness.FRESH),
            ("oci rotation credential", check_freshness.FRESH),
        ]

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(SystemExit(1), id="missing-cached-credential"),
            pytest.param(requests.HTTPError("401 Client Error"), id="token-request-rejected"),
            pytest.param(KeyError("access_token"), id="token-response-without-a-token"),
        ],
    )
    def test_auth_failure_fails_every_leaf_entry_but_not_the_rotation_credential_check(self, oci_client_factory, vault, error):
        vault.seed("_rotation-key-oci-created-at", datetime.now(UTC).isoformat(), category="rotation")
        oci_client_factory.side_effect = error

        results = check_freshness.check_oci()

        statuses = {name: status for name, status, _ in results}
        assert statuses["oci write"] == check_freshness.CHECK_FAILED
        assert statuses["oci read"] == check_freshness.CHECK_FAILED
        # What the alert shows for each leaf is the cause of the failure.
        details = {name: detail for name, _, detail in results}
        assert details["oci write"] == details["oci read"] == str(error)
        # The rotation credential's own check is self-tracked and
        # doesn't depend on the SCIM client at all — an OAuth2 auth
        # failure for the leaf checks shouldn't also break this one.
        assert statuses["oci rotation credential"] == check_freshness.FRESH


class TestCheckR2:
    @pytest.fixture(autouse=True)
    def _seeded(self, vault):
        vault.seed("_rotation-key-cloudflare-r2-token", "admin-token", category="rotation")
        vault.seed("cloudflare-r2-account-id", "acct123")
        vault.seed("cloudflare-r2-write-access-key", "TOKEN_ID_WRITE")
        vault.seed("cloudflare-r2-read-access-key", "TOKEN_ID_READ")

    def test_fresh_and_stale_and_rotation_token_all_reported(self, session_class):
        session = session_class.return_value
        future = (datetime.now(UTC) + timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        past = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        def get(url, timeout=None):
            if url.endswith("/user/tokens/verify"):
                return response(json_body={"success": True, "result": {"id": "x", "status": "active", "expires_on": future}})
            if "TOKEN_ID_WRITE" in url:
                return response(json_body={"success": True, "result": {"expires_on": future}})
            if "TOKEN_ID_READ" in url:
                return response(json_body={"success": True, "result": {"expires_on": past}})
            raise AssertionError(f"unexpected URL: {url}")

        session.get.side_effect = get

        results = check_freshness.check_r2()

        statuses = {name: status for name, status, _ in results}
        assert statuses["r2 write"] == check_freshness.FRESH
        assert statuses["r2 read"] == check_freshness.STALE
        assert statuses["r2 rotation token"] == check_freshness.FRESH

    def test_requests_carry_the_cached_rotation_token_as_a_bearer_header(self, session_class):
        session = session_class.return_value
        session.get.return_value = response(json_body={"success": True, "result": {"expires_on": "2099-01-01T00:00:00Z"}})

        check_freshness.check_r2()

        assert session.headers["Authorization"] == "Bearer admin-token"

    def test_every_cloudflare_request_has_a_timeout(self, session_class):
        session = session_class.return_value
        session.get.return_value = response(json_body={"success": True, "result": {"expires_on": "2099-01-01T00:00:00Z"}})

        check_freshness.check_r2()

        assert len(session.get.call_args_list) == 3
        assert all(has_a_timeout(call) for call in session.get.call_args_list)

    @pytest.mark.parametrize(
        ("name", "category", "missing"),
        [
            pytest.param("_rotation-key-cloudflare-r2-token", "rotation", "rotation token", id="only-the-token-missing"),
            pytest.param("cloudflare-r2-account-id", "leaf", "account id", id="only-the-account-id-missing"),
        ],
    )
    def test_either_missing_credential_fails_all_three_entries_and_is_named(self, session_class, vault, name, category, missing):
        vault.delete(name, category=category)

        results = check_freshness.check_r2()

        assert [(label, status) for label, status, _ in results] == [
            (f"r2 {entry}", check_freshness.CHECK_FAILED) for entry in ("write", "read", "rotation token")
        ]
        assert all(f"no cached {missing} " in detail for _, _, detail in results)
        session_class.assert_not_called()

    def test_rotation_token_is_a_user_token_not_an_account_token(self, session_class):
        """The rotation token is a Cloudflare User API Token (My
        Profile > API Tokens), not an Account Owned one -
        /accounts/{account_id}/tokens/verify and List Tokens both only
        ever see the Account-owned category and would never find this
        token no matter how they're queried. /user/tokens/verify is the
        only endpoint that can actually check it, and needs no
        account_id to do so."""
        session = session_class.return_value

        def get(url, timeout=None):
            if url == "https://api.cloudflare.com/client/v4/user/tokens/verify":
                return response(json_body={"success": True, "result": {"id": "x", "status": "active", "expires_on": "2099-01-01T00:00:00Z"}})
            raise AssertionError(f"check_r2 must not call the account-scoped tokens endpoints for the rotation token: {url}")

        session.get.side_effect = get

        result = check_freshness._r2_rotation_token_result(session)

        assert result[0] == "r2 rotation token"
        assert result[1] == check_freshness.FRESH

    def test_rotation_token_verify_failure_is_check_failed(self, session_class):
        session = session_class.return_value
        session.get.return_value = response(json_body={"success": False, "errors": [{"code": 1000, "message": "Invalid API Token"}]})

        result = check_freshness._r2_rotation_token_result(session)

        assert result[1] == check_freshness.CHECK_FAILED

    def test_missing_rotation_token_never_prompts_and_reports_check_failed(self, vault):
        # Overwrite setUp's seeded token — this test wants the "nothing
        # cached" path, not the happy path.
        vault.delete("_rotation-key-cloudflare-r2-token", category="rotation")

        with patch("getpass.getpass", autospec=True) as mock_prompt:
            results = check_freshness.check_r2()

        mock_prompt.assert_not_called()
        assert all(status == check_freshness.CHECK_FAILED for _, status, _ in results)


@pytest.mark.usefixtures("fake_vault")
class TestMainExitCode:
    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.STALE, "old")], autospec=True)
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.FRESH, "")], autospec=True)
    def test_stale_alone_does_not_fail_the_run(self, mock_b2, mock_oci, mock_r2):
        # Matches backup_agent's check-freshness.sh: ordinary expiry is
        # an alert to read in the journal, not a run failure — only an
        # actual check error should make the unit itself fail.
        assert check_freshness.main() == 0

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.CHECK_FAILED, "boom")], autospec=True)
    def test_check_failure_fails_the_run(self, mock_b2, mock_oci, mock_r2):
        assert check_freshness.main() == 1


class TestTelegramAlert:
    @pytest.fixture(autouse=True)
    def _telegram_credentials(self, fake_vault):
        seed_telegram(fake_vault, "telegram-token", "123:abc")
        seed_telegram(fake_vault, "telegram-chat-id", "-100999")

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness.requests, "post", autospec=True)
    def test_all_fresh_sends_no_telegram_message(self, mock_post, mock_b2, mock_oci, mock_r2):
        # The whole point of alerting only on non-fresh outcomes: a
        # healthy weekly run shouldn't page anyone.
        assert check_freshness.main() == 0
        mock_post.assert_not_called()

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.WARNING, "expires in 5d")], autospec=True)
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness.requests, "post", autospec=True)
    def test_warning_alone_still_sends_a_telegram_alert(self, mock_post, mock_b2, mock_oci, mock_r2, fake_vault):
        # This is the actual point of adding WARNING — a checked-fine
        # "past its window" result used to not even alert; a "expiring
        # soon" result must, since it's the only outcome that gives any
        # lead time before B2/R2 actually reject the credential.
        seed_telegram(fake_vault, "telegram-topic-id-backups", "42")
        mock_post.return_value = response()

        check_freshness.main()

        mock_post.assert_called_once()
        url, kwargs = mock_post.call_args.args[0], mock_post.call_args.kwargs
        assert "bot123:abc/sendMessage" in url
        assert kwargs["data"]["chat_id"] == "-100999"
        assert kwargs["data"]["message_thread_id"] == "42"
        assert "oci write" in kwargs["data"]["text"]

    @patch.object(check_freshness.requests, "post", autospec=True)
    def test_the_send_has_a_timeout(self, mock_post):
        mock_post.return_value = response()

        check_freshness._send_telegram_alert(["<b>oci write</b>: past its window"])

        mock_post.assert_called_once()
        assert has_a_timeout(mock_post.call_args)

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.STALE, "old")], autospec=True)
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness.requests, "post", autospec=True)
    def test_no_topic_id_cached_omits_the_param_instead_of_sending_empty(self, mock_post, mock_b2, mock_oci, mock_r2):
        # Telegram's API rejects message_thread_id outright if it's
        # passed empty rather than ignoring it (see
        # docs/topics/monitoring/telegram-notifications.md) - must be omitted, not "".
        mock_post.return_value = response()
        check_freshness.main()
        assert "message_thread_id" not in mock_post.call_args.kwargs["data"]

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.STALE, "old")], autospec=True)
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness.requests, "post", autospec=True)
    def test_missing_telegram_credentials_does_not_crash_the_run(self, mock_post, mock_b2, mock_oci, mock_r2, fake_vault):
        delete_telegram(fake_vault, "telegram-token")
        rc = check_freshness.main()
        mock_post.assert_not_called()
        assert rc == 0  # STALE alone still doesn't fail the run, even unalerted

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness, "check_b2", return_value=[("b2 write", check_freshness.CHECK_FAILED, "boom")], autospec=True)
    @patch.object(check_freshness.requests, "post", autospec=True)
    def test_uses_html_parse_mode_not_legacy_markdown(self, mock_post, mock_b2, mock_oci, mock_r2):
        """Legacy Markdown fails twice over here: an unescaped underscore
        in the static header makes Telegram reject the alert (400), and
        an escaped one inside the bold *...* span renders as a literal
        backslash, because Telegram does not allow escaping inside
        entities. HTML mode has neither problem. This checks the
        parse_mode and tag shape actually sent, not just that a message
        went out."""
        mock_post.return_value = response()
        check_freshness.main()
        data = mock_post.call_args.kwargs["data"]
        assert data["parse_mode"] == "HTML"
        assert "<b>cloud_credentials freshness check</b>" in data["text"]
        assert "\\_" not in data["text"]  # no leftover Markdown-escape artifact

    @patch.object(check_freshness, "check_r2", return_value=[("r2 write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(check_freshness, "check_oci", return_value=[("oci write", check_freshness.FRESH, "")], autospec=True)
    @patch.object(
        check_freshness,
        "check_b2",
        return_value=[("b2 write", check_freshness.CHECK_FAILED, "provider said <b>bad</b> & broken")],
        autospec=True,
    )
    @patch.object(check_freshness.requests, "post", autospec=True)
    def test_detail_containing_html_special_chars_is_escaped(self, mock_post, mock_b2, mock_oci, mock_r2):
        # Detail strings embed arbitrary provider error text and URLs -
        # unlike telegram_notify's other callers (all static templates),
        # this one will eventually interpolate a literal &, <, or > and
        # must not let it be interpreted as real markup.
        mock_post.return_value = response()
        check_freshness.main()
        text = mock_post.call_args.kwargs["data"]["text"]
        assert "provider said &lt;b&gt;bad&lt;/b&gt; &amp; broken" in text
        assert "<b>bad</b>" not in text
