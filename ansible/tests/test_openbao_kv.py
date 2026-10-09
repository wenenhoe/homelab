"""Unit tests for module_utils/openbao_kv.py.

Run via `uv run pytest ansible/tests/ -v`. hvac.Client is the library's own
with its network calls stubbed, so what the code reads from and sends to the
client is the real call shape.
"""

from __future__ import annotations

import configparser
import re
import uuid
from pathlib import Path
from unittest.mock import create_autospec

import hvac
import openbao_kv
import pytest
import requests

ANSIBLE_DIR = Path(__file__).resolve().parent.parent
PATH = "hosts/security/example-secret"
MOUNT = "secret"


@pytest.fixture
def hvac_client() -> hvac.Client:
    """A real hvac.Client whose network calls are autospec'd stand-ins.

    Every request funnels through the adapter, so nothing can leave the
    process; the two KV v2 calls the code makes are stubbed on top with their
    real signatures. token starts as None so a token in the environment never
    reaches a test.
    """
    client = hvac.Client(url="https://openbao.example.com:8200")
    client.token = None
    for name in ("request", "get", "post", "put", "delete", "list"):
        setattr(client.adapter, name, create_autospec(getattr(client.adapter, name)))
    for name in ("read_secret_version", "create_or_update_secret"):
        setattr(client.secrets.kv.v2, name, create_autospec(getattr(client.secrets.kv.v2, name)))
    return client


def _stored(value: str) -> dict:
    return {"data": {"data": {"value": value}}}


def _read(client: hvac.Client):
    return client.secrets.kv.v2.read_secret_version


def _write(client: hvac.Client):
    return client.secrets.kv.v2.create_or_update_secret


def _written_value(client: hvac.Client) -> str:
    return _write(client).call_args.kwargs["secret"]["value"]


def test_ansible_cfg_names_the_module_utils_directory():
    cfg = configparser.ConfigParser()
    cfg.read(ANSIBLE_DIR / "ansible.cfg")
    assert (ANSIBLE_DIR / cfg["defaults"]["module_utils"]).resolve() == Path(openbao_kv.__file__).resolve().parent


class TestGenerateValue:
    @pytest.mark.parametrize("length", [1, 2, 39, 40, 41])
    def test_hex_is_exactly_the_requested_length_in_hex_characters(self, length):
        value = openbao_kv.generate_value("hex", length)
        assert len(value) == length
        assert re.fullmatch(r"[0-9a-f]+", value)

    def test_uuid4_is_a_version_4_uuid(self):
        value = openbao_kv.generate_value("uuid4", None)
        assert str(uuid.UUID(value)) == value
        assert uuid.UUID(value).version == 4

    @pytest.mark.parametrize("source", ["hex", "uuid4"])
    def test_two_calls_give_different_values(self, source):
        assert openbao_kv.generate_value(source, 40) != openbao_kv.generate_value(source, 40)

    @pytest.mark.parametrize("length", [None, 0, -4])
    def test_hex_without_a_positive_length_is_rejected(self, length):
        with pytest.raises(ValueError, match="positive length"):
            openbao_kv.generate_value("hex", length)

    def test_an_unknown_source_is_rejected(self):
        with pytest.raises(ValueError, match="unsupported source 'base64'"):
            openbao_kv.generate_value("base64", 40)


class TestReadValue:
    def test_returns_the_stored_value(self, hvac_client):
        _read(hvac_client).return_value = _stored("stored-value")

        assert openbao_kv.read_value(hvac_client, PATH, MOUNT) == "stored-value"
        _read(hvac_client).assert_called_once_with(path=PATH, mount_point=MOUNT, raise_on_deleted_version=True)

    def test_a_missing_path_reads_as_none(self, hvac_client):
        _read(hvac_client).side_effect = hvac.exceptions.InvalidPath()

        assert openbao_kv.read_value(hvac_client, PATH, MOUNT) is None

    def test_any_other_error_propagates(self, hvac_client):
        _read(hvac_client).side_effect = hvac.exceptions.Forbidden("permission denied")

        with pytest.raises(hvac.exceptions.Forbidden, match="permission denied"):
            openbao_kv.read_value(hvac_client, PATH, MOUNT)


class TestEnsureValue:
    def test_an_existing_secret_is_returned_and_nothing_is_written(self, hvac_client):
        _read(hvac_client).return_value = _stored("already-there")

        assert openbao_kv.ensure_value(hvac_client, PATH, MOUNT, "hex", 40) == ("already-there", False)
        _write(hvac_client).assert_not_called()

    def test_a_missing_hex_secret_is_generated_and_stored_with_cas_zero(self, hvac_client):
        _read(hvac_client).side_effect = hvac.exceptions.InvalidPath()

        resolved = openbao_kv.ensure_value(hvac_client, PATH, MOUNT, "hex", 40)

        stored = _written_value(hvac_client)
        assert resolved == (stored, True)
        assert re.fullmatch(r"[0-9a-f]{40}", stored)
        _write(hvac_client).assert_called_once_with(path=PATH, secret={"value": stored}, cas=0, mount_point=MOUNT)

    def test_a_missing_uuid4_secret_is_generated_and_stored(self, hvac_client):
        _read(hvac_client).side_effect = hvac.exceptions.InvalidPath()

        resolved = openbao_kv.ensure_value(hvac_client, PATH, MOUNT, "uuid4", None)

        stored = _written_value(hvac_client)
        assert resolved == (stored, True)
        assert uuid.UUID(stored).version == 4

    def test_a_lost_create_race_returns_the_winners_value_not_the_generated_one(self, hvac_client):
        _read(hvac_client).side_effect = [hvac.exceptions.InvalidPath(), _stored("winners-value")]
        _write(hvac_client).side_effect = hvac.exceptions.InvalidRequest("check-and-set parameter did not match the current version")

        resolved = openbao_kv.ensure_value(hvac_client, PATH, MOUNT, "hex", 40)

        assert resolved == ("winners-value", False)
        assert resolved.value != _written_value(hvac_client)
        assert _read(hvac_client).call_count == 2

    def test_a_rejected_write_that_leaves_the_path_empty_fails_with_the_original_error(self, hvac_client):
        _read(hvac_client).side_effect = hvac.exceptions.InvalidPath()
        rejection = hvac.exceptions.InvalidRequest("secret too large")
        _write(hvac_client).side_effect = rejection

        with pytest.raises(openbao_kv.SecretNotStoredError, match="still empty: secret too large") as caught:
            openbao_kv.ensure_value(hvac_client, PATH, MOUNT, "hex", 40)
        assert caught.value.__cause__ is rejection

    def test_a_write_error_other_than_a_conflict_propagates_without_a_reread(self, hvac_client):
        _read(hvac_client).side_effect = hvac.exceptions.InvalidPath()
        _write(hvac_client).side_effect = hvac.exceptions.Forbidden("permission denied")

        with pytest.raises(hvac.exceptions.Forbidden, match="permission denied"):
            openbao_kv.ensure_value(hvac_client, PATH, MOUNT, "hex", 40)
        _read(hvac_client).assert_called_once()

    def test_an_invalid_length_fails_before_anything_is_written(self, hvac_client):
        _read(hvac_client).side_effect = hvac.exceptions.InvalidPath()

        with pytest.raises(ValueError, match="positive length"):
            openbao_kv.ensure_value(hvac_client, PATH, MOUNT, "hex", 0)
        _write(hvac_client).assert_not_called()


class TestNewClient:
    def test_points_at_the_url_with_the_token_and_the_ca_bundle(self):
        client = openbao_kv.new_client("https://openbao.example.com:8200", "a-token", "/etc/ca.pem")

        assert client.adapter.base_uri == "https://openbao.example.com:8200"
        assert client.token == "a-token"
        assert client.adapter.session.verify == "/etc/ca.pem"

    def test_without_a_ca_bundle_it_verifies_against_the_system_store(self):
        client = openbao_kv.new_client("https://openbao.example.com:8200", "a-token", None)

        assert client.adapter.session.verify is True


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(hvac.exceptions.Forbidden("denied"), id="vault-api-error"),
        pytest.param(requests.exceptions.ConnectionError("refused"), id="unreachable-server"),
        pytest.param(openbao_kv.SecretNotStoredError("empty"), id="rejected-write"),
        pytest.param(ValueError("bad length"), id="invalid-value"),
    ],
)
def test_expected_errors_covers_what_a_failed_exchange_raises(error):
    assert isinstance(error, openbao_kv.EXPECTED_ERRORS)
