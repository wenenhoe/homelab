"""Unit tests for openbao_utils.bao_session.

Run via `uv run pytest tools/tests/ -v`. Every subprocess/SSH/Vault
call is mocked; nothing here spawns a real shell, touches a real
`security` host, or a real OpenBao. fetch_root_cert/vault_login come
from utils.repo/openbao_utils.client - tested once, directly, in their
own test files. This file only tests bao_session.py's own remaining
logic: the version check, session spawning, main()'s wiring, and
SIGHUP-triggered cleanup (ADR 0033).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from openbao_utils import bao_session


class LocalBaoVersionTests(unittest.TestCase):
    @patch("openbao_utils.bao_session.subprocess.run")
    def test_extracts_the_dotted_version(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], returncode=0, stdout=b"OpenBao v2.6.2 (dd9c19c37a878cf4a81b18efb8d6f0599c7da923)")
        self.assertEqual(bao_session.local_bao_version(), "2.6.2")

    @patch("openbao_utils.bao_session.subprocess.run")
    def test_returns_none_on_unparseable_output(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], returncode=0, stdout=b"not a version string")
        self.assertIsNone(bao_session.local_bao_version())

    @patch("openbao_utils.bao_session.subprocess.run")
    def test_returns_none_on_nonzero_exit(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], returncode=127, stdout=b"")
        self.assertIsNone(bao_session.local_bao_version())

    @patch("openbao_utils.bao_session.subprocess.run", side_effect=FileNotFoundError)
    def test_returns_none_when_bao_isnt_installed(self, mock_run):
        self.assertIsNone(bao_session.local_bao_version())


class ServerVersionTests(unittest.TestCase):
    def test_returns_the_version_field_from_a_dict_response(self):
        mock_client = MagicMock()
        mock_client.sys.read_health_status.return_value = {"initialized": True, "sealed": False, "version": "2.6.2"}
        self.assertEqual(bao_session.server_version(mock_client), "2.6.2")

    def test_returns_none_for_a_non_dict_response(self):
        # hvac's JSONAdapter only decodes a 200 into a dict - a sealed
        # (503) or uninitialized (501) server comes back as a raw
        # requests.Response instead, per openbao.org's own /sys/health
        # docs. Treated the same as any other read failure here.
        mock_client = MagicMock()
        mock_client.sys.read_health_status.return_value = MagicMock(name="requests.Response")
        self.assertIsNone(bao_session.server_version(mock_client))

    def test_returns_none_on_any_exception(self):
        mock_client = MagicMock()
        mock_client.sys.read_health_status.side_effect = RuntimeError("boom")
        self.assertIsNone(bao_session.server_version(mock_client))


class WarnOnVersionMismatchTests(unittest.TestCase):
    @patch.object(bao_session, "server_version", return_value="2.6.1")
    @patch.object(bao_session, "local_bao_version", return_value="2.6.2")
    def test_warns_on_mismatch(self, _mock_local, _mock_remote):
        with patch("sys.stderr") as mock_stderr:
            bao_session.warn_on_version_mismatch(MagicMock())
        written = "".join(c.args[0] for c in mock_stderr.write.call_args_list if c.args)
        self.assertIn("2.6.2", written)
        self.assertIn("2.6.1", written)

    @patch.object(bao_session, "server_version", return_value="2.6.2")
    @patch.object(bao_session, "local_bao_version", return_value="2.6.2")
    def test_silent_on_match(self, _mock_local, _mock_remote):
        with patch("sys.stderr") as mock_stderr:
            bao_session.warn_on_version_mismatch(MagicMock())
        mock_stderr.write.assert_not_called()

    @patch.object(bao_session, "server_version", return_value=None)
    @patch.object(bao_session, "local_bao_version", return_value="2.6.2")
    def test_silent_when_either_side_is_unknown(self, _mock_local, _mock_remote):
        with patch("sys.stderr") as mock_stderr:
            bao_session.warn_on_version_mismatch(MagicMock())
        mock_stderr.write.assert_not_called()


class SpawnSessionTests(unittest.TestCase):
    @patch("openbao_utils.bao_session.subprocess.call", return_value=0)
    def test_spawns_the_env_shell(self, mock_call):
        env = {"SHELL": "/bin/zsh", "BAO_TOKEN": "x"}
        self.assertEqual(bao_session.spawn_session(env), 0)
        mock_call.assert_called_once_with(["/bin/zsh"], env=env)

    @patch("openbao_utils.bao_session.subprocess.call")
    def test_defaults_to_bin_sh_when_shell_isnt_set(self, mock_call):
        bao_session.spawn_session({})
        mock_call.assert_called_once_with(["/bin/sh"], env={})

    @patch("openbao_utils.bao_session.subprocess.call", side_effect=KeyboardInterrupt)
    def test_ctrl_c_returns_130_instead_of_raising(self, mock_call):
        self.assertEqual(bao_session.spawn_session({"SHELL": "/bin/sh"}), 130)


class RevokeTests(unittest.TestCase):
    """_revoke's own idempotency guard, isolated from main()'s wiring -
    both the finally block and the SIGHUP handler can reach it for the
    same session (ADR 0033)."""

    def test_clears_the_token_after_revoking(self):
        mock_client = MagicMock()
        mock_client.token = "fake-token"
        bao_session._revoke(mock_client)
        mock_client.auth.token.revoke_self.assert_called_once()
        self.assertIsNone(mock_client.token)

    def test_a_second_call_is_a_silent_no_op(self):
        mock_client = MagicMock()
        mock_client.token = None  # as if _revoke already ran once
        bao_session._revoke(mock_client)
        mock_client.auth.token.revoke_self.assert_not_called()

    def test_tolerates_a_client_that_never_logged_in(self):
        bao_session._revoke(None)  # must not raise


class MainTests(unittest.TestCase):
    """hvac.Client, vault_login, and the root-cert fetch are all
    mocked - this only tests main()'s own wiring: argv parsing, env
    construction, and that cleanup (revoke + temp-file removal) always
    runs."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_client.token = "fake-token"

        patchers = {
            "hvac_client_cls": patch("openbao_utils.bao_session.hvac.Client", return_value=self.mock_client),
            "vault_login": patch.object(bao_session, "vault_login"),
            "fetch_root_cert": patch.object(bao_session, "fetch_root_cert", return_value="fake-root-ca-pem"),
            "warn": patch.object(bao_session, "warn_on_version_mismatch"),
            "spawn": patch.object(bao_session, "spawn_session", return_value=0),
            "getpass": patch("openbao_utils.bao_session.getpass.getpass", return_value="fake-secret-id"),
            "base_url": patch.object(bao_session, "openbao_base_url", return_value="https://openbao.example.com:8200"),
            "hostname": patch.object(bao_session, "openbao_hostname", return_value="openbao.example.com"),
        }
        self.mocks = {name: p.start() for name, p in patchers.items()}
        for p in patchers.values():
            self.addCleanup(p.stop)

    def run_main(self, argv):
        with patch.object(sys, "argv", argv):
            return bao_session.main()

    def test_logs_in_with_the_given_role_id_and_prompted_secret_id(self):
        self.run_main(["bao_session.py", "some-role-id"])
        self.mocks["vault_login"].assert_called_once_with(self.mock_client, "some-role-id", "fake-secret-id")

    def test_fetches_the_root_cert_fresh_over_ssh(self):
        self.run_main(["bao_session.py", "some-role-id"])
        self.mocks["fetch_root_cert"].assert_called_once()

    def test_spawns_with_bao_env_vars_set_from_the_login(self):
        captured_env = {}

        def spy(env):
            captured_env.update(env)
            # Checked from inside the spawn call, before main()'s own
            # finally-block cleanup deletes it.
            captured_env["_ca_existed_during_session"] = Path(env["BAO_CACERT"]).exists()
            return 0

        self.mocks["spawn"].side_effect = spy
        self.run_main(["bao_session.py", "some-role-id"])
        self.assertEqual(captured_env["BAO_ADDR"], "https://openbao.example.com:8200")
        self.assertEqual(captured_env["BAO_TLS_SERVER_NAME"], "openbao.example.com")
        self.assertEqual(captured_env["BAO_TOKEN"], "fake-token")
        self.assertTrue(captured_env["_ca_existed_during_session"])

    def test_returns_the_spawned_shells_exit_code(self):
        self.mocks["spawn"].return_value = 7
        self.assertEqual(self.run_main(["bao_session.py", "some-role-id"]), 7)

    def test_revokes_the_token_after_the_session_ends(self):
        self.run_main(["bao_session.py", "some-role-id"])
        self.mock_client.auth.token.revoke_self.assert_called_once()

    def test_deletes_the_temp_ca_file_after_the_session_ends(self):
        captured_paths = []

        def spy(env):
            captured_paths.append(env["BAO_CACERT"])
            return 0

        self.mocks["spawn"].side_effect = spy
        self.run_main(["bao_session.py", "some-role-id"])
        self.assertFalse(Path(captured_paths[0]).exists())

    def test_does_not_revoke_when_login_itself_fails(self):
        # A real hvac.Client's own .token stays None until a login call
        # actually sets it - mimicked here since vault_login is mocked
        # out and would otherwise leave setUp's placeholder token in
        # place despite the "failed" login.
        self.mock_client.token = None
        self.mocks["vault_login"].side_effect = RuntimeError("bad credentials")
        with self.assertRaises(RuntimeError):
            self.run_main(["bao_session.py", "some-role-id"])
        self.mock_client.auth.token.revoke_self.assert_not_called()

    def test_still_deletes_the_temp_ca_file_when_login_itself_fails(self):
        self.mock_client.token = None
        self.mocks["vault_login"].side_effect = RuntimeError("bad credentials")
        with patch("openbao_utils.bao_session.Path") as mock_path_cls, self.assertRaises(RuntimeError):
            self.run_main(["bao_session.py", "some-role-id"])
        mock_path_cls.return_value.unlink.assert_called_once_with(missing_ok=True)

    def test_revoke_failure_doesnt_prevent_the_session_from_completing(self):
        self.mock_client.auth.token.revoke_self.side_effect = RuntimeError("network blip")
        with patch("sys.stderr"):
            result = self.run_main(["bao_session.py", "some-role-id"])
        self.assertEqual(result, 0)

    def test_sighup_mid_session_still_revokes_and_removes_the_ca_file(self):
        # Actually raises real SIGHUP against this test process while
        # spawn_session is "running", rather than calling the internal
        # handler directly - the whole point (ADR 0033) is that
        # Python's own signal delivery interrupts a blocking call and
        # still runs cleanup, which a direct call wouldn't exercise.
        captured = {}

        def spy(env):
            captured["ca_path"] = env["BAO_CACERT"]
            os.kill(os.getpid(), signal.SIGHUP)
            return 0  # unreachable if the handler does its job

        self.mocks["spawn"].side_effect = spy
        with self.assertRaises(SystemExit) as ctx:
            self.run_main(["bao_session.py", "some-role-id"])
        self.assertEqual(ctx.exception.code, 1)
        self.mock_client.auth.token.revoke_self.assert_called_once()
        self.assertFalse(Path(captured["ca_path"]).exists())


if __name__ == "__main__":
    unittest.main()
