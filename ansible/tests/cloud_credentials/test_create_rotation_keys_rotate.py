"""Unit tests for create_rotation_keys.py's --rotate flag: validation
and dispatch only - the actual rotate_*/create_* logic is covered in
tests/cloud_credentials/rotation_keys/.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials import create_rotation_keys


def test_rotate_with_provider_all_is_a_usage_error(monkeypatch):
    # --rotate reissues one provider's rotation key at a time - "all"
    # would mean prompting for two different master credentials in one
    # run with no way to report a partial failure cleanly.
    monkeypatch.setattr(sys, "argv", ["prog", "--rotate", "--provider", "all"])
    with pytest.raises(SystemExit):
        create_rotation_keys.main()


@patch("cloud_credentials.create_rotation_keys.rotate_b2_rotation_key", return_value=True)
@patch("cloud_credentials.create_rotation_keys.create_b2_rotation_key")
def test_rotate_provider_b2_calls_rotate_not_create(mock_create, mock_rotate, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["prog", "--rotate", "--provider", "b2"])
    monkeypatch.setattr(create_rotation_keys, "SECRETS_DIR", tmp_path)

    rc = create_rotation_keys.main()

    mock_rotate.assert_called_once()
    mock_create.assert_not_called()
    assert rc == 0


@patch("cloud_credentials.create_rotation_keys.rotate_oci_rotation_key", return_value=False)
def test_rotate_provider_oci_passes_admin_email_and_reports_failure(mock_rotate, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["prog", "--rotate", "--provider", "oci", "--admin-email", "you@example.com"])
    monkeypatch.setattr(create_rotation_keys, "SECRETS_DIR", tmp_path)

    rc = create_rotation_keys.main()

    mock_rotate.assert_called_once_with("you@example.com")
    # rotate_oci_rotation_key returning False must surface as a failed run.
    assert rc == 1


@patch("cloud_credentials.create_rotation_keys.create_b2_rotation_key")
@patch("cloud_credentials.create_rotation_keys.create_oci_rotation_key")
def test_plain_run_without_rotate_still_uses_create_path(mock_create_oci, mock_create_b2, monkeypatch, tmp_path):
    # Regression check: adding --rotate must not change the default,
    # already-relied-upon idempotent bootstrap behavior.
    monkeypatch.setattr(sys, "argv", ["prog", "--provider", "all", "--admin-email", "you@example.com"])
    monkeypatch.setattr(create_rotation_keys, "SECRETS_DIR", tmp_path)

    create_rotation_keys.main()

    mock_create_b2.assert_called_once()
    mock_create_oci.assert_called_once()


@patch("cloud_credentials.create_rotation_keys.cache_r2_rotation_token")
@patch("cloud_credentials.create_rotation_keys.create_b2_rotation_key")
@patch("cloud_credentials.create_rotation_keys.create_oci_rotation_key")
def test_provider_all_never_touches_r2(mock_create_oci, mock_create_b2, mock_cache_r2, monkeypatch, tmp_path):
    # r2 needs a Console step the operator may not have done yet -
    # --provider all must never block on it implicitly.
    monkeypatch.setattr(sys, "argv", ["prog", "--provider", "all", "--admin-email", "you@example.com"])
    monkeypatch.setattr(create_rotation_keys, "SECRETS_DIR", tmp_path)

    create_rotation_keys.main()

    mock_cache_r2.assert_not_called()


@patch("cloud_credentials.create_rotation_keys.cache_r2_rotation_token")
def test_provider_r2_without_rotate_calls_cache_not_rotate(mock_cache_r2, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["prog", "--provider", "r2"])
    monkeypatch.setattr(create_rotation_keys, "SECRETS_DIR", tmp_path)

    rc = create_rotation_keys.main()

    mock_cache_r2.assert_called_once()
    assert rc == 0


@patch("cloud_credentials.create_rotation_keys.rotate_r2_rotation_token", return_value=True)
def test_rotate_provider_r2_is_a_valid_combination(mock_rotate, monkeypatch, tmp_path):
    # This is the actual feature request: --rotate --provider r2 must
    # work, not just b2/oci, so updating the cached Console token never
    # needs manual cache-file editing again.
    monkeypatch.setattr(sys, "argv", ["prog", "--rotate", "--provider", "r2"])
    monkeypatch.setattr(create_rotation_keys, "SECRETS_DIR", tmp_path)

    rc = create_rotation_keys.main()

    mock_rotate.assert_called_once()
    assert rc == 0
