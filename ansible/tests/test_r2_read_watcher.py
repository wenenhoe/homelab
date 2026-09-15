"""Unit tests for r2_read_watcher.py.

Run via `uv run pytest ansible/tests/ -v`. Imports across the
docker/openbao/watcher boundary deliberately - that script is
hand-installed, not part of the ansible/ package tree, but still
gets real test coverage like everything else in this repo.

Fixture lines below are copied verbatim from a real audit-log capture
against a live 2.6.2 instance (the spike that grounded ADR 0026's
watcher design) - not synthesized, so the exact field shapes are
trustworthy.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import hvac

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docker" / "openbao" / "watcher"))

import r2_read_watcher as watcher

REAL_R2_REQUEST_LINE = (
    '{"time":"2026-09-09T06:12:11.937092952Z","type":"request","auth":{"client_token":"hmac-sha256:x",'
    '"accessor":"hmac-sha256:y","display_name":"approle","policies":["controller","default"],'
    '"token_policies":["controller","default"],"policy_results":{"allowed":true,"granting_policies":'
    '[{"name":"controller","namespace_id":"root","type":"acl"}]},"metadata":{"role_name":"controller"},'
    '"entity_id":"5cb4e785-fe8a-5d82-b991-31e74980d2b8","token_type":"service","token_ttl":3600,'
    '"token_issue_time":"2026-09-09T13:54:37+08:00"},"request":{"id":"c85c8c0a-fe1e-1905-3969-05389499a36e",'
    '"client_id":"5cb4e785-fe8a-5d82-b991-31e74980d2b8","operation":"read","mount_point":"secret/",'
    '"mount_type":"kv","mount_running_version":"v2.6.2+builtin.bao","mount_class":"secret",'
    '"client_token":"hmac-sha256:x","client_token_accessor":"hmac-sha256:y","namespace":{"id":"root"},'
    '"path":"secret/data/cloud_credentials/rotation/_rotation-key-cloudflare-r2-token",'
    '"remote_address":"127.0.0.1","remote_port":50326}}'
)

REAL_R2_RESPONSE_LINE = (
    '{"time":"2026-09-09T06:12:11.93737049Z","type":"response","auth":{"client_token":"hmac-sha256:x",'
    '"display_name":"approle","metadata":{"role_name":"controller"}},"request":{"operation":"read",'
    '"path":"secret/data/cloud_credentials/rotation/_rotation-key-cloudflare-r2-token"},'
    '"response":{"data":{"data":{"value":"hmac-sha256:z"}}}}'
)

REAL_UNRELATED_LINE = (
    '{"time":"2026-09-09T06:11:55.374857106Z","type":"request","auth":{"policy_results":{"allowed":true},'
    '"token_type":"default"},"request":{"id":"6d29a0c9-8215-cbba-c7cf-cdd8270f45b1","operation":"read",'
    '"mount_point":"sys/","mount_type":"system","path":"sys/internal/ui/mounts/secret",'
    '"remote_address":"127.0.0.1","remote_port":45854}}'
)


class MatchR2ReadTests(unittest.TestCase):
    def test_matches_a_real_request_line_for_the_r2_token(self):
        match = watcher.match_r2_read(REAL_R2_REQUEST_LINE)
        self.assertIsNotNone(match)
        self.assertEqual(match["role_name"], "controller")
        self.assertEqual(match["display_name"], "approle")
        self.assertEqual(match["remote_address"], "127.0.0.1")

    def test_ignores_the_response_line_for_the_same_read(self):
        self.assertIsNone(watcher.match_r2_read(REAL_R2_RESPONSE_LINE))

    def test_ignores_an_unrelated_path(self):
        self.assertIsNone(watcher.match_r2_read(REAL_UNRELATED_LINE))

    def test_ignores_malformed_json_without_raising(self):
        self.assertIsNone(watcher.match_r2_read("not json at all {{{"))

    def test_ignores_an_empty_line_without_raising(self):
        self.assertIsNone(watcher.match_r2_read(""))

    def test_ignores_valid_json_that_is_not_a_dict(self):
        self.assertIsNone(watcher.match_r2_read("[1, 2, 3]"))

    def test_ignores_a_write_to_the_same_path(self):
        write_line = REAL_R2_REQUEST_LINE.replace('"operation":"read"', '"operation":"update"')
        self.assertIsNone(watcher.match_r2_read(write_line))


class SendAlertTests(unittest.TestCase):
    @patch("r2_read_watcher.requests.post")
    def test_includes_topic_id_when_present(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        telegram = {"token": "t", "chat_id": "c", "topic_id": "42"}
        match = {"time": "now", "role_name": "controller", "display_name": "approle", "remote_address": "1.2.3.4"}

        watcher.send_alert(telegram, match)

        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"]["message_thread_id"], "42")

    @patch("r2_read_watcher.requests.post")
    def test_omits_topic_id_when_blank(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        telegram = {"token": "t", "chat_id": "c", "topic_id": ""}
        match = {"time": "now", "role_name": "controller", "display_name": "approle", "remote_address": "1.2.3.4"}

        watcher.send_alert(telegram, match)

        _, kwargs = mock_post.call_args
        self.assertNotIn("message_thread_id", kwargs["data"])

    @patch("r2_read_watcher.requests.post")
    def test_escapes_html_special_characters_in_match_fields(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        telegram = {"token": "t", "chat_id": "c", "topic_id": ""}
        match = {"time": "now", "role_name": "<script>", "display_name": "approle", "remote_address": "1.2.3.4"}

        watcher.send_alert(telegram, match)

        _, kwargs = mock_post.call_args
        self.assertNotIn("<script>", kwargs["data"]["text"])
        self.assertIn("&lt;script&gt;", kwargs["data"]["text"])

    @patch("r2_read_watcher.requests.post", side_effect=watcher.requests.RequestException("boom"))
    def test_a_failed_send_does_not_raise(self, mock_post):
        telegram = {"token": "t", "chat_id": "c", "topic_id": ""}
        match = {"time": "now", "role_name": "controller", "display_name": "approle", "remote_address": "1.2.3.4"}
        watcher.send_alert(telegram, match)  # should not raise


class WatchTests(unittest.TestCase):
    @patch("r2_read_watcher._save_state")
    @patch("r2_read_watcher.subprocess.Popen")
    def test_calls_send_alert_exactly_once_for_a_matching_line(self, mock_popen, mock_save_state):
        mock_proc = Mock()
        mock_proc.stdout = iter([REAL_R2_REQUEST_LINE + "\n", REAL_UNRELATED_LINE + "\n"])
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        with patch("r2_read_watcher.send_alert") as mock_send:
            rc = watcher.watch({"token": "t", "chat_id": "c", "topic_id": ""}, None)

        self.assertEqual(rc, 0)
        mock_send.assert_called_once()

    @patch("r2_read_watcher._save_state")
    @patch("r2_read_watcher.subprocess.Popen")
    def test_never_alerts_when_telegram_secrets_are_unavailable(self, mock_popen, mock_save_state):
        mock_proc = Mock()
        mock_proc.stdout = iter([REAL_R2_REQUEST_LINE + "\n"])
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        with patch("r2_read_watcher.send_alert") as mock_send:
            watcher.watch(None, None)

        mock_send.assert_not_called()


class VaultLoginTests(unittest.TestCase):
    def test_logs_in_with_the_given_role_and_secret_id(self):
        mock_client = MagicMock()

        watcher._vault_login(mock_client, "some-role-id", "some-secret-id")

        mock_client.auth.approle.login.assert_called_once_with(role_id="some-role-id", secret_id="some-secret-id")


class ReadVaultSecretTests(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()

    def test_returns_none_on_invalid_path(self):
        self.mock_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
        self.assertIsNone(watcher._read_vault_secret(self.mock_client, "telegram-token"))

    def test_returns_value_on_success(self):
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "the-token"}}}
        self.assertEqual(watcher._read_vault_secret(self.mock_client, "telegram-token"), "the-token")

    def test_uses_the_telegram_scope_and_mount(self):
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        watcher._read_vault_secret(self.mock_client, "telegram-token")
        self.mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="hosts/all/telegram/telegram-token",
            mount_point=watcher.VAULT_KV_MOUNT,
            raise_on_deleted_version=True,
        )


class FetchTelegramSecretsTests(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()

    def _stub_reads(self, values: dict[str, str | None]) -> None:
        def fake_read_secret_version(path: str, **_: object) -> dict:
            name = path.rsplit("/", 1)[-1]
            if values.get(name) is None:
                raise hvac.exceptions.InvalidPath
            return {"data": {"data": {"value": values[name]}}}

        self.mock_client.secrets.kv.v2.read_secret_version.side_effect = fake_read_secret_version

    def test_returns_none_when_token_missing(self):
        self._stub_reads({"telegram-token": None, "telegram-chat-id": "c"})
        self.assertIsNone(watcher._fetch_telegram_secrets(self.mock_client))

    def test_returns_none_when_chat_id_missing(self):
        self._stub_reads({"telegram-token": "t", "telegram-chat-id": None})
        self.assertIsNone(watcher._fetch_telegram_secrets(self.mock_client))

    def test_returns_secrets_with_empty_topic_id_when_absent(self):
        self._stub_reads({"telegram-token": "t", "telegram-chat-id": "c", "telegram-topic-id-backups": None})
        secrets = watcher._fetch_telegram_secrets(self.mock_client)
        self.assertEqual(secrets, {"token": "t", "chat_id": "c", "topic_id": ""})

    def test_returns_secrets_with_topic_id_when_present(self):
        self._stub_reads({"telegram-token": "t", "telegram-chat-id": "c", "telegram-topic-id-backups": "42"})
        secrets = watcher._fetch_telegram_secrets(self.mock_client)
        self.assertEqual(secrets, {"token": "t", "chat_id": "c", "topic_id": "42"})


class MainTests(unittest.TestCase):
    @patch("r2_read_watcher.watch", return_value=0)
    @patch("r2_read_watcher._load_state", return_value=None)
    @patch("r2_read_watcher._fetch_telegram_secrets")
    @patch("r2_read_watcher._vault_login")
    @patch("r2_read_watcher.hvac.Client")
    @patch("r2_read_watcher._read_file", side_effect=["some-role-id", "some-secret-id"])
    def test_builds_one_client_and_threads_it_through_login_and_fetch(
        self, mock_read_file, mock_client_cls, mock_login, mock_fetch, mock_load_state, mock_watch
    ):
        watcher.main()

        client_arg = mock_client_cls.return_value
        mock_login.assert_called_once_with(client_arg, "some-role-id", "some-secret-id")
        mock_fetch.assert_called_once_with(client_arg)
        _, kwargs = mock_client_cls.call_args
        self.assertEqual(kwargs["url"], watcher.OPENBAO_BASE_URL)
        self.assertEqual(kwargs["verify"], False)
        self.assertEqual(kwargs["timeout"], watcher._TIMEOUT_SECONDS)

    @patch("r2_read_watcher.watch", return_value=0)
    @patch("r2_read_watcher._load_state", return_value=None)
    @patch("r2_read_watcher._fetch_telegram_secrets", return_value={"token": "t", "chat_id": "c", "topic_id": ""})
    @patch("r2_read_watcher._vault_login")
    @patch("r2_read_watcher.hvac.Client")
    @patch("r2_read_watcher._read_file", side_effect=["some-role-id", "some-secret-id"])
    def test_passes_fetched_telegram_secrets_and_prior_state_to_watch(
        self, mock_read_file, mock_client_cls, mock_login, mock_fetch, mock_load_state, mock_watch
    ):
        watcher.main()

        mock_watch.assert_called_once_with({"token": "t", "chat_id": "c", "topic_id": ""}, None)


if __name__ == "__main__":
    unittest.main()
