"""Unit tests for cloud_credentials.cache.

Run via `uv run pytest ansible/tests/ -v`. Every SSH/Vault call is
mocked; nothing here touches a real `security` host or a real OpenBao.
Mirrors ansible/tests/test_bootstrap_secrets.py's own mocking style for
the equivalent (deliberately duplicated, not shared) plumbing.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials import cache


def _mock_response(status_code: int, json_body: dict | None = None):
    resp = MagicMock(status_code=status_code)
    resp.json.return_value = json_body or {}
    resp.raise_for_status = MagicMock() if status_code < 400 else MagicMock(side_effect=requests.exceptions.HTTPError(str(status_code)))
    return resp


class SecretsDirTestCase(unittest.TestCase):
    """Base for anything touching SECRETS_DIR - main-domain and the
    controller AppRole credential are always read from here, regardless
    of which Vault path is under test. Also resets the process-lifetime
    session singleton, since it would otherwise leak a mocked token/ca_path
    across tests that don't expect one."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        dir_patcher = patch.object(cache, "SECRETS_DIR", self.tmp)
        dir_patcher.start()
        self.addCleanup(dir_patcher.stop)
        session_patcher = patch.object(cache, "_session", None)
        session_patcher.start()
        self.addCleanup(session_patcher.stop)

    def seed(self, name: str, value: str) -> None:
        (self.tmp / name).write_text(value)


class MainDomainTests(SecretsDirTestCase):
    def test_raises_system_exit_when_missing(self):
        with self.assertRaises(SystemExit):
            cache._main_domain()

    def test_returns_stripped_value(self):
        self.seed("main-domain", "  example.com  \n")
        self.assertEqual(cache._main_domain(), "example.com")


class OpenbaoBaseUrlTests(SecretsDirTestCase):
    def test_builds_expected_url(self):
        self.seed("main-domain", "example.com")
        self.assertEqual(cache._openbao_base_url(), "https://openbao.sec.lan.example.com:8200")


class FetchRootCertTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        patcher = patch.object(
            cache,
            "_security_ssh_target",
            return_value=("secadmin", "security.internal.example.com", "/home/x/.ssh/key"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("cloud_credentials.cache.subprocess.run")
    def test_returns_stdout_on_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="-----BEGIN CERTIFICATE-----\n...", stderr="")
        cert = cache._fetch_root_cert()
        self.assertIn("BEGIN CERTIFICATE", cert)

    @patch("cloud_credentials.cache.subprocess.run")
    def test_raises_system_exit_on_nonzero_returncode(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Permission denied")
        with self.assertRaises(SystemExit):
            cache._fetch_root_cert()


class VaultLoginTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")

    def test_raises_system_exit_when_role_id_missing(self):
        self.seed("openbao-controller-secret-id", "some-secret-id")
        with self.assertRaises(SystemExit):
            cache._vault_login("/dev/null")

    @patch("cloud_credentials.cache.requests.post")
    def test_returns_client_token_on_success(self, mock_post):
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "some-secret-id")
        mock_post.return_value = _mock_response(200, {"auth": {"client_token": "s.abc123"}})

        token = cache._vault_login("/path/to/ca.crt")

        self.assertEqual(token, "s.abc123")
        mock_post.assert_called_once_with(
            "https://openbao.sec.lan.example.com:8200/v1/auth/approle/login",
            json={"role_id": "some-role-id", "secret_id": "some-secret-id"},
            verify="/path/to/ca.crt",
            timeout=10,
        )


class GetSessionTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "some-secret-id")
        patch.object(cache, "_fetch_root_cert", return_value="fake-cert").start()
        self.addCleanup(patch.stopall)

    @patch("cloud_credentials.cache.requests.post")
    def test_logs_in_only_once_across_multiple_calls(self, mock_post):
        mock_post.return_value = _mock_response(200, {"auth": {"client_token": "s.abc123"}})
        cache._get_session()
        cache._get_session()
        cache._get_session()
        mock_post.assert_called_once()

    @patch("cloud_credentials.cache.requests.post")
    def test_session_carries_token_and_ca_path(self, mock_post):
        mock_post.return_value = _mock_response(200, {"auth": {"client_token": "s.abc123"}})
        session = cache._get_session()
        self.assertEqual(session["token"], "s.abc123")
        self.assertTrue(Path(session["ca_path"]).exists())


class VaultPathTests(unittest.TestCase):
    def test_builds_leaf_path(self):
        self.assertEqual(cache._vault_path("leaf", "backblaze-b2-write-access-key"), "cloud_credentials/leaf/backblaze-b2-write-access-key")

    def test_builds_rotation_path(self):
        self.assertEqual(cache._vault_path("rotation", "_rotation-key-cloudflare-r2-token"), "cloud_credentials/rotation/_rotation-key-cloudflare-r2-token")

    def test_rejects_unknown_category(self):
        with self.assertRaises(ValueError):
            cache._vault_path("bogus", "some-key")


class ScopedReadWriteTests(SecretsDirTestCase):
    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "some-secret-id")
        patch.object(cache, "_fetch_root_cert", return_value="fake-cert").start()
        patch.object(cache, "_vault_login", return_value="s.abc123").start()
        self.addCleanup(patch.stopall)
        self.cached, self.read_cache, self.write_cache, self.require_cache_file = cache.scoped("leaf")

    @patch("cloud_credentials.cache.requests.get")
    def test_read_cache_returns_none_on_404(self, mock_get):
        mock_get.return_value = _mock_response(404)
        self.assertIsNone(self.read_cache("does-not-exist"))

    @patch("cloud_credentials.cache.requests.get")
    def test_read_cache_returns_value_on_200(self, mock_get):
        mock_get.return_value = _mock_response(200, {"data": {"data": {"value": "the-value"}}})
        self.assertEqual(self.read_cache("some-key"), "the-value")

    @patch("cloud_credentials.cache.requests.get")
    def test_read_cache_uses_the_leaf_path(self, mock_get):
        mock_get.return_value = _mock_response(200, {"data": {"data": {"value": "x"}}})
        self.read_cache("backblaze-b2-write-access-key")
        mock_get.assert_called_once_with(
            f"https://openbao.sec.lan.example.com:8200/v1/{cache.VAULT_KV_MOUNT}/data/cloud_credentials/leaf/backblaze-b2-write-access-key",
            headers={"X-Vault-Token": "s.abc123"},
            verify=mock_get.call_args.kwargs["verify"],
            timeout=10,
        )

    @patch("cloud_credentials.cache.requests.get")
    def test_cached_false_on_404(self, mock_get):
        mock_get.return_value = _mock_response(404)
        self.assertFalse(self.cached("does-not-exist"))

    @patch("cloud_credentials.cache.requests.get")
    def test_cached_true_on_200(self, mock_get):
        mock_get.return_value = _mock_response(200, {"data": {"data": {"value": "x"}}})
        self.assertTrue(self.cached("some-key"))

    @patch("cloud_credentials.cache.requests.post")
    def test_write_cache_posts_the_correct_payload(self, mock_post):
        mock_post.return_value = _mock_response(200)
        self.write_cache("some-key", "the-value")
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"], {"X-Vault-Token": "s.abc123"})
        self.assertEqual(kwargs["json"], {"data": {"value": "the-value"}})

    @patch("cloud_credentials.cache.requests.get")
    def test_require_cache_file_exits_with_message_when_missing(self, mock_get):
        mock_get.return_value = _mock_response(404)
        with self.assertRaises(SystemExit):
            self.require_cache_file("missing-key", "run some-command to create it")

    @patch("cloud_credentials.cache.requests.get")
    def test_require_cache_file_returns_value_when_present(self, mock_get):
        mock_get.return_value = _mock_response(200, {"data": {"data": {"value": "present-value"}}})
        self.assertEqual(self.require_cache_file("present-key", "unused"), "present-value")


class ScopedRotationCategoryTests(SecretsDirTestCase):
    """One test confirming scoped("rotation") writes under the other
    top-level path - the leaf-side behavior is already exercised in
    detail by ScopedReadWriteTests above, and the two categories only
    differ in which _vault_path prefix gets used."""

    def setUp(self):
        super().setUp()
        self.seed("main-domain", "example.com")
        self.seed("openbao-controller-role-id", "some-role-id")
        self.seed("openbao-controller-secret-id", "some-secret-id")
        patch.object(cache, "_fetch_root_cert", return_value="fake-cert").start()
        patch.object(cache, "_vault_login", return_value="s.abc123").start()
        self.addCleanup(patch.stopall)

    @patch("cloud_credentials.cache.requests.get")
    def test_read_cache_uses_the_rotation_path(self, mock_get):
        mock_get.return_value = _mock_response(200, {"data": {"data": {"value": "x"}}})
        _, read_cache, _, _ = cache.scoped("rotation")
        read_cache("_rotation-key-cloudflare-r2-token")
        called_url = mock_get.call_args.args[0]
        self.assertIn("cloud_credentials/rotation/_rotation-key-cloudflare-r2-token", called_url)


class ScopedUnknownCategoryTests(unittest.TestCase):
    def test_raises_on_unknown_category(self):
        with self.assertRaises(ValueError):
            cache.scoped("bogus")


if __name__ == "__main__":
    unittest.main()
