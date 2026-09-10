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
from unittest.mock import Mock, patch

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


if __name__ == "__main__":
    unittest.main()
