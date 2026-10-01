"""Tests for the fixtures in tools/tests/conftest.py and the helpers beside it."""

from __future__ import annotations

import pytest
import requests
from _responses import response
from utils import repo


def test_secrets_dir_starts_empty(secrets_dir):
    assert repo.read_bootstrap_file("main-domain") is None


def test_secrets_dir_serves_seeded_files_to_the_code_under_test(secrets_dir):
    secrets_dir.seed("main-domain", "  seeded.example \n")

    assert repo.read_bootstrap_file("main-domain") == "seeded.example"
    assert (secrets_dir.path / "main-domain").read_text() == "  seeded.example \n"


def test_secrets_dir_path_does_not_embed_the_test_name(secrets_dir, request):
    assert request.node.name[:20] not in str(secrets_dir.path)


def test_response_serves_the_status_and_json_body_it_was_given():
    resp = response(201, {"id": "x"})

    assert resp.status_code == 201
    assert resp.json() == {"id": "x"}


def test_response_serves_a_plain_text_body():
    assert response(403, text="insufficient_scope").text == "insufficient_scope"


def test_response_raises_http_error_for_a_4xx_and_not_for_a_2xx():
    assert response(204).raise_for_status() is None
    with pytest.raises(requests.HTTPError, match="403"):
        response(403).raise_for_status()


def test_response_refuses_both_a_json_body_and_text():
    with pytest.raises(ValueError, match="not both"):
        response(200, {"a": 1}, "b")
