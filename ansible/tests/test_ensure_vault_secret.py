"""Unit tests for roles/secrets/library/ensure_vault_secret.py.

Run via `uv run pytest ansible/tests/ -v`. The module runs under the real
AnsibleModule, fed its arguments the way Ansible's own tests do
(`patch_module_args`), so what it prints is what a task would receive. The
module imports its shared code as ansible.module_utils.openbao_kv, a name that
only resolves inside an Ansible run, so the fixture binds it to the file.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import uuid
from unittest.mock import create_autospec

import hvac
import openbao_kv
import pytest
import requests
from ansible.module_utils.testing import patch_module_args

TOKEN = "s.example-token"
REDACTED = "VALUE_SPECIFIED_IN_NO_LOG_PARAMETER"


def _args(*, drop: tuple[str, ...] = (), **overrides) -> dict:
    args = {
        "name": "example-secret",
        "source": "hex",
        "length": 40,
        "scope": "hosts/security",
        "vault_base_url": "https://openbao.example.com:8200",
        "vault_token": TOKEN,
        "vault_ca_path": "/etc/ca.pem",
    }
    return {key: value for key, value in {**args, **overrides}.items() if key not in drop}


@pytest.fixture
def hvac_client() -> hvac.Client:
    """A real hvac.Client whose network calls are autospec'd stand-ins.

    Every request funnels through the adapter, so nothing can leave the
    process; the two KV v2 calls the module makes are stubbed on top with
    their real signatures. token starts as None so a token in the environment
    never reaches a test.
    """
    client = hvac.Client(url="https://openbao.example.com:8200")
    client.token = None
    for name in ("request", "get", "post", "put", "delete", "list"):
        setattr(client.adapter, name, create_autospec(getattr(client.adapter, name)))
    for name in ("read_secret_version", "create_or_update_secret"):
        setattr(client.secrets.kv.v2, name, create_autospec(getattr(client.secrets.kv.v2, name)))
    return client


@pytest.fixture
def module(monkeypatch: pytest.MonkeyPatch, hvac_client: hvac.Client):
    """The module under test, bound to the shared code and to `hvac_client`."""
    monkeypatch.setitem(sys.modules, "ansible.module_utils.openbao_kv", openbao_kv)
    monkeypatch.delitem(sys.modules, "ensure_vault_secret", raising=False)
    mod = importlib.import_module("ensure_vault_secret")
    monkeypatch.setattr(mod, "new_client", create_autospec(openbao_kv.new_client, return_value=hvac_client))
    return mod


def _run(module, capsys, args: dict) -> tuple[int, dict]:
    with patch_module_args(args), pytest.raises(SystemExit) as exit_info:
        module.main()
    return exit_info.value.code, json.loads(capsys.readouterr().out)


def _read(client: hvac.Client):
    return client.secrets.kv.v2.read_secret_version


def _write(client: hvac.Client):
    return client.secrets.kv.v2.create_or_update_secret


def _missing(client: hvac.Client) -> None:
    _read(client).side_effect = hvac.exceptions.InvalidPath()


def _stored(value: str) -> dict:
    return {"data": {"data": {"value": value}}}


class TestResolvedSecret:
    def test_a_missing_hex_secret_is_created_and_its_real_value_returned(self, module, hvac_client, capsys):
        _missing(hvac_client)

        code, result = _run(module, capsys, _args())

        stored = _write(hvac_client).call_args.kwargs["secret"]["value"]
        assert code == 0
        assert (result["changed"], result["generated"]) == (True, True)
        assert result["value"] == stored
        assert re.fullmatch(r"[0-9a-f]{40}", stored)

    def test_a_missing_uuid4_secret_is_created(self, module, hvac_client, capsys):
        _missing(hvac_client)

        code, result = _run(module, capsys, _args(source="uuid4", length=None))

        assert code == 0
        assert (result["changed"], result["generated"]) == (True, True)
        assert uuid.UUID(result["value"]).version == 4
        assert result["value"] == _write(hvac_client).call_args.kwargs["secret"]["value"]

    def test_an_existing_secret_is_returned_unchanged_and_nothing_is_written(self, module, hvac_client, capsys):
        _read(hvac_client).return_value = _stored("already-there")

        code, result = _run(module, capsys, _args())

        assert code == 0
        assert (result["changed"], result["generated"], result["value"]) == (False, False, "already-there")
        _write(hvac_client).assert_not_called()

    def test_a_lost_create_race_returns_the_winners_value_and_reports_no_change(self, module, hvac_client, capsys):
        _read(hvac_client).side_effect = [hvac.exceptions.InvalidPath(), _stored("winners-value")]
        _write(hvac_client).side_effect = hvac.exceptions.InvalidRequest("check-and-set parameter did not match the current version")

        code, result = _run(module, capsys, _args())

        assert code == 0
        assert (result["changed"], result["generated"], result["value"]) == (False, False, "winners-value")

    def test_the_secret_is_looked_up_at_scope_and_name_on_the_given_mount(self, module, hvac_client, capsys):
        _read(hvac_client).return_value = _stored("v")

        _run(module, capsys, _args(scope="hosts/all/telegram", name="bot-token", kv_mount="kv"))

        _read(hvac_client).assert_called_once_with(path="hosts/all/telegram/bot-token", mount_point="kv", raise_on_deleted_version=True)

    def test_the_mount_defaults_to_secret(self, module, hvac_client, capsys):
        _read(hvac_client).return_value = _stored("v")

        _run(module, capsys, _args())

        assert _read(hvac_client).call_args.kwargs["mount_point"] == "secret"

    def test_the_client_is_built_from_the_connection_arguments(self, module, hvac_client, capsys):
        _read(hvac_client).return_value = _stored("v")

        _run(module, capsys, _args())

        module.new_client.assert_called_once_with("https://openbao.example.com:8200", TOKEN, "/etc/ca.pem")


class TestSecretsStayOutOfTheOutput:
    def test_the_token_is_not_printed_on_success(self, module, hvac_client, capsys):
        _read(hvac_client).return_value = _stored("v")
        with patch_module_args(_args()), pytest.raises(SystemExit):
            module.main()

        assert TOKEN not in capsys.readouterr().out

    def test_the_returned_value_is_the_secret_not_a_redaction_marker(self, module, hvac_client, capsys):
        _read(hvac_client).return_value = _stored("the-real-secret")

        _, result = _run(module, capsys, _args())

        assert result["value"] == "the-real-secret"
        assert REDACTED not in json.dumps(result)

    def test_an_error_message_that_quotes_the_token_is_redacted(self, module, hvac_client, capsys):
        _missing(hvac_client)
        _write(hvac_client).side_effect = hvac.exceptions.Forbidden(f"permission denied for token {TOKEN}")
        with patch_module_args(_args()), pytest.raises(SystemExit):
            module.main()
        printed = capsys.readouterr().out

        assert TOKEN not in printed
        assert "permission denied for token" in json.loads(printed)["msg"]


class TestFailures:
    @pytest.mark.parametrize(
        ("error", "reason"),
        [
            pytest.param(hvac.exceptions.Forbidden("permission denied"), "permission denied", id="vault-api-error"),
            pytest.param(requests.exceptions.ConnectionError("connection refused"), "connection refused", id="unreachable-server"),
        ],
    )
    def test_a_failed_read_fails_the_task_naming_the_secret(self, module, hvac_client, capsys, error, reason):
        _read(hvac_client).side_effect = error

        code, result = _run(module, capsys, _args())

        assert code == 1
        assert result["failed"] is True
        assert result["msg"].startswith("hosts/security/example-secret: ")
        assert reason in result["msg"]

    def test_a_rejected_write_that_leaves_the_path_empty_fails_the_task(self, module, hvac_client, capsys):
        _missing(hvac_client)
        _write(hvac_client).side_effect = hvac.exceptions.InvalidRequest("secret too large")

        code, result = _run(module, capsys, _args())

        assert code == 1
        assert "still empty: secret too large" in result["msg"]

    @pytest.mark.parametrize(
        ("changes", "reason"),
        [
            pytest.param({"drop": ("length",)}, "length", id="hex-without-a-length"),
            pytest.param({"length": 0}, "positive length", id="hex-with-a-zero-length"),
            pytest.param({"source": "base64"}, "value of source must be one of: hex, uuid4", id="unknown-source"),
            pytest.param({"drop": ("vault_token",)}, "missing required arguments: vault_token", id="no-token"),
        ],
    )
    def test_bad_arguments_fail_the_task_without_writing(self, module, hvac_client, capsys, changes, reason):
        _missing(hvac_client)

        code, result = _run(module, capsys, _args(**changes))

        assert code == 1
        assert reason in result["msg"]
        _write(hvac_client).assert_not_called()

    def test_check_mode_is_skipped_without_touching_vault(self, module, hvac_client, capsys):
        code, result = _run(module, capsys, _args(_ansible_check_mode=True))

        assert code == 0
        assert result["skipped"] is True
        module.new_client.assert_not_called()
