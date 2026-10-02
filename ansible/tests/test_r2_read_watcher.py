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

from unittest.mock import create_autospec, patch

import hvac
import pytest
import r2_read_watcher as watcher
import requests

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


@pytest.fixture
def hvac_client() -> hvac.Client:
    """A real hvac.Client whose network calls are autospec'd stand-ins.

    Every request funnels through the adapter, so nothing can leave the
    process; the calls the watcher makes are stubbed on top with their real
    signatures. token starts as None so a token in the environment never
    reaches a test.
    """
    client = hvac.Client(url=watcher.OPENBAO_BASE_URL)
    client.token = None
    for name in ("request", "get", "post", "put", "delete", "list"):
        setattr(client.adapter, name, create_autospec(getattr(client.adapter, name)))
    for owner, name in ((client.secrets.kv.v2, "read_secret_version"), (client.auth.approle, "login")):
        setattr(owner, name, create_autospec(getattr(owner, name)))
    return client


def _ok_response() -> requests.Response:
    resp = requests.Response()
    resp.status_code = 200
    return resp


class TestMatchR2Read:
    def test_matches_a_real_request_line_for_the_r2_token(self):
        match = watcher.match_r2_read(REAL_R2_REQUEST_LINE)
        assert match is not None
        assert match["role_name"] == "controller"
        assert match["display_name"] == "approle"
        assert match["remote_address"] == "127.0.0.1"

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param(REAL_R2_RESPONSE_LINE, id="response-line-for-the-same-read"),
            pytest.param(REAL_UNRELATED_LINE, id="unrelated-path"),
            pytest.param("not json at all {{{", id="malformed-json"),
            pytest.param("", id="empty-line"),
            pytest.param("[1, 2, 3]", id="json-that-is-not-a-dict"),
            pytest.param(REAL_R2_REQUEST_LINE.replace('"operation":"read"', '"operation":"update"'), id="write-to-the-same-path"),
        ],
    )
    def test_ignores_a_line_that_is_not_a_read_of_the_r2_token(self, line):
        assert watcher.match_r2_read(line) is None


class TestSendAlert:
    @patch("r2_read_watcher.requests.post", autospec=True)
    def test_includes_topic_id_when_present(self, mock_post):
        mock_post.return_value = _ok_response()
        telegram = {"token": "t", "chat_id": "c", "topic_id": "42"}
        match = {"time": "now", "role_name": "controller", "display_name": "approle", "remote_address": "1.2.3.4"}

        watcher.send_alert(telegram, match)

        _, kwargs = mock_post.call_args
        assert kwargs["data"]["message_thread_id"] == "42"

    @patch("r2_read_watcher.requests.post", autospec=True)
    def test_omits_topic_id_when_blank(self, mock_post):
        mock_post.return_value = _ok_response()
        telegram = {"token": "t", "chat_id": "c", "topic_id": ""}
        match = {"time": "now", "role_name": "controller", "display_name": "approle", "remote_address": "1.2.3.4"}

        watcher.send_alert(telegram, match)

        _, kwargs = mock_post.call_args
        assert "message_thread_id" not in kwargs["data"]

    @patch("r2_read_watcher.requests.post", autospec=True)
    def test_escapes_html_special_characters_in_match_fields(self, mock_post):
        mock_post.return_value = _ok_response()
        telegram = {"token": "t", "chat_id": "c", "topic_id": ""}
        match = {"time": "now", "role_name": "<script>", "display_name": "approle", "remote_address": "1.2.3.4"}

        watcher.send_alert(telegram, match)

        _, kwargs = mock_post.call_args
        assert "<script>" not in kwargs["data"]["text"]
        assert "&lt;script&gt;" in kwargs["data"]["text"]

    @patch("r2_read_watcher.requests.post", side_effect=watcher.requests.RequestException("boom"), autospec=True)
    def test_a_failed_send_is_reported_on_stderr_not_raised(self, mock_post, capsys):
        telegram = {"token": "t", "chat_id": "c", "topic_id": ""}
        match = {"time": "now", "role_name": "controller", "display_name": "approle", "remote_address": "1.2.3.4"}

        watcher.send_alert(telegram, match)

        assert "telegram: alert send failed: boom" in capsys.readouterr().err


class TestWatch:
    @patch("r2_read_watcher._save_state", autospec=True)
    @patch("r2_read_watcher.subprocess.Popen", autospec=True)
    def test_calls_send_alert_exactly_once_for_a_matching_line_and_returns_the_docker_logs_exit_code(self, mock_popen, mock_save_state):
        mock_proc = mock_popen.return_value
        mock_proc.stdout = iter([REAL_R2_REQUEST_LINE + "\n", REAL_UNRELATED_LINE + "\n"])
        mock_proc.wait.return_value = 3

        with patch("r2_read_watcher.send_alert", autospec=True) as mock_send:
            rc = watcher.watch({"token": "t", "chat_id": "c", "topic_id": ""}, None)

        assert rc == 3
        mock_send.assert_called_once()

    @patch("r2_read_watcher._save_state", autospec=True)
    @patch("r2_read_watcher.subprocess.Popen", autospec=True)
    def test_never_alerts_when_telegram_secrets_are_unavailable(self, mock_popen, mock_save_state, capsys):
        mock_proc = mock_popen.return_value
        mock_proc.stdout = iter([REAL_R2_REQUEST_LINE + "\n"])
        mock_proc.wait.return_value = 3

        with patch("r2_read_watcher.send_alert", autospec=True) as mock_send:
            rc = watcher.watch(None, None)

        assert rc == 3
        assert "R2 admin token read" in capsys.readouterr().err
        mock_send.assert_not_called()


class TestVaultLogin:
    def test_logs_in_with_the_given_role_and_secret_id(self, hvac_client):
        watcher._vault_login(hvac_client, "some-role-id", "some-secret-id")

        hvac_client.auth.approle.login.assert_called_once_with(role_id="some-role-id", secret_id="some-secret-id")


class TestReadVaultSecret:
    def test_returns_none_on_invalid_path(self, hvac_client):
        hvac_client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
        assert watcher._read_vault_secret(hvac_client, "telegram-token") is None

    def test_returns_value_on_success(self, hvac_client):
        hvac_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "the-token"}}}
        assert watcher._read_vault_secret(hvac_client, "telegram-token") == "the-token"

    def test_uses_the_telegram_scope_and_mount(self, hvac_client):
        hvac_client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": {"value": "x"}}}
        watcher._read_vault_secret(hvac_client, "telegram-token")
        hvac_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="hosts/all/telegram/telegram-token",
            mount_point=watcher.VAULT_KV_MOUNT,
            raise_on_deleted_version=True,
        )


class TestFetchTelegramSecrets:
    @pytest.fixture
    def stub_reads(self, hvac_client):
        def _stub_reads(values: dict[str, str | None]) -> None:
            def fake_read_secret_version(path: str, **_: object) -> dict:
                name = path.rsplit("/", 1)[-1]
                if values.get(name) is None:
                    raise hvac.exceptions.InvalidPath
                return {"data": {"data": {"value": values[name]}}}

            hvac_client.secrets.kv.v2.read_secret_version.side_effect = fake_read_secret_version

        return _stub_reads

    def test_returns_none_when_token_missing(self, hvac_client, stub_reads):
        stub_reads({"telegram-token": None, "telegram-chat-id": "c"})
        assert watcher._fetch_telegram_secrets(hvac_client) is None

    def test_returns_none_when_chat_id_missing(self, hvac_client, stub_reads):
        stub_reads({"telegram-token": "t", "telegram-chat-id": None})
        assert watcher._fetch_telegram_secrets(hvac_client) is None

    def test_returns_secrets_with_empty_topic_id_when_absent(self, hvac_client, stub_reads):
        stub_reads({"telegram-token": "t", "telegram-chat-id": "c", "telegram-topic-id-backups": None})
        secrets = watcher._fetch_telegram_secrets(hvac_client)
        assert secrets == {"token": "t", "chat_id": "c", "topic_id": ""}

    def test_returns_secrets_with_topic_id_when_present(self, hvac_client, stub_reads):
        stub_reads({"telegram-token": "t", "telegram-chat-id": "c", "telegram-topic-id-backups": "42"})
        secrets = watcher._fetch_telegram_secrets(hvac_client)
        assert secrets == {"token": "t", "chat_id": "c", "topic_id": "42"}


class TestMain:
    @patch("r2_read_watcher.watch", return_value=0, autospec=True)
    @patch("r2_read_watcher._load_state", return_value=None, autospec=True)
    @patch("r2_read_watcher._fetch_telegram_secrets", autospec=True)
    @patch("r2_read_watcher._vault_login", autospec=True)
    @patch("r2_read_watcher.hvac.Client", autospec=True)
    @patch("r2_read_watcher._read_file", side_effect=["some-role-id", "some-secret-id"], autospec=True)
    def test_builds_one_client_and_threads_it_through_login_and_fetch(
        self, mock_read_file, mock_client_cls, mock_login, mock_fetch, mock_load_state, mock_watch
    ):
        watcher.main()

        client_arg = mock_client_cls.return_value
        mock_login.assert_called_once_with(client_arg, "some-role-id", "some-secret-id")
        mock_fetch.assert_called_once_with(client_arg)
        _, kwargs = mock_client_cls.call_args
        assert kwargs["url"] == watcher.OPENBAO_BASE_URL
        assert kwargs["verify"] is False
        assert kwargs["timeout"] == watcher._TIMEOUT_SECONDS

    @patch("r2_read_watcher.watch", return_value=0, autospec=True)
    @patch("r2_read_watcher._load_state", return_value=None, autospec=True)
    @patch("r2_read_watcher._fetch_telegram_secrets", return_value={"token": "t", "chat_id": "c", "topic_id": ""}, autospec=True)
    @patch("r2_read_watcher._vault_login", autospec=True)
    @patch("r2_read_watcher.hvac.Client", autospec=True)
    @patch("r2_read_watcher._read_file", side_effect=["some-role-id", "some-secret-id"], autospec=True)
    def test_passes_fetched_telegram_secrets_and_prior_state_to_watch(
        self, mock_read_file, mock_client_cls, mock_login, mock_fetch, mock_load_state, mock_watch
    ):
        watcher.main()

        mock_watch.assert_called_once_with({"token": "t", "chat_id": "c", "topic_id": ""}, None)
