"""Unit tests for rotate_leaf_keys.py: every provider's two leaves are rotated,
one provider failing does not stop the others, and the exit status says so.

The rotate_* logic itself is covered in tests/cloud_credentials/leaf_keys/.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import sys
from unittest.mock import create_autospec

import pytest
import requests
from _responses import response
from cloud_credentials import rotate_leaf_keys

PROVIDERS = ("b2", "oci", "r2")


@pytest.fixture
def rotators(monkeypatch):
    """The three providers' rotate functions, each reporting success; a test changes one's outcome."""
    fns = {name: create_autospec(getattr(rotate_leaf_keys, f"rotate_{name}"), return_value=True) for name in PROVIDERS}
    for name, fn in fns.items():
        monkeypatch.setattr(rotate_leaf_keys, f"rotate_{name}", fn)
    monkeypatch.setattr(sys, "argv", ["prog"])
    return fns


def test_rotates_both_leaves_of_every_provider(rotators, capsys):
    rc = rotate_leaf_keys.main()

    assert rc == 0
    for fn in rotators.values():
        fn.assert_called_once_with(["write", "read"])
    assert capsys.readouterr().err == ""


def test_a_failed_verification_does_not_stop_the_providers_after_it(rotators, capsys):
    rotators["b2"].return_value = False

    rc = rotate_leaf_keys.main()

    assert rc == 1
    rotators["oci"].assert_called_once_with(["write", "read"])
    rotators["r2"].assert_called_once_with(["write", "read"])
    assert capsys.readouterr().err == "rotation failed for: b2\n"


@pytest.mark.parametrize(
    ("raised", "reported"),
    [
        # cache.py and the leaf modules sys.exit after printing what is missing
        pytest.param(SystemExit(1), "oci: stopped before finishing", id="exits-after-reporting-a-missing-secret"),
        # R2's fallback prompt for its admin token, where a job has no input to give it
        pytest.param(EOFError(), "oci: rotation failed: EOFError", id="prompt-with-no-input"),
        pytest.param(requests.HTTPError(response=response(403, text="denied")), "oci: request failed: 403 denied", id="provider-http-error"),
    ],
)
def test_a_provider_that_raises_does_not_stop_the_others(rotators, capsys, raised, reported):
    rotators["oci"].side_effect = raised

    rc = rotate_leaf_keys.main()

    assert rc == 1
    rotators["b2"].assert_called_once_with(["write", "read"])
    rotators["r2"].assert_called_once_with(["write", "read"])
    err = capsys.readouterr().err
    assert reported in err
    assert err.endswith("rotation failed for: oci\n")


def test_every_failed_provider_is_named(rotators, capsys):
    rotators["b2"].return_value = False
    rotators["r2"].side_effect = SystemExit(1)

    rc = rotate_leaf_keys.main()

    assert rc == 1
    assert capsys.readouterr().err.endswith("rotation failed for: b2, r2\n")


def test_arguments_are_refused_and_nothing_rotates(rotators, monkeypatch):
    # A mistyped --provider must not quietly rotate all three.
    monkeypatch.setattr(sys, "argv", ["prog", "--provider", "b2"])

    with pytest.raises(SystemExit) as exit_info:
        rotate_leaf_keys.main()

    assert exit_info.value.code == 2
    for fn in rotators.values():
        fn.assert_not_called()
