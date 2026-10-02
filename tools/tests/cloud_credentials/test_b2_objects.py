"""Tests for the b2sdk helpers in _b2_objects.py and the b2_api fixture."""

from __future__ import annotations

import pytest
from _b2_objects import application_key, bucket, full_application_key, stubbed_b2_api
from b2sdk.v2 import B2Api


def test_a_full_application_key_keeps_its_id_as_id_underscore():
    key = full_application_key("KEY_ID", "APP_KEY")

    assert (key.id_, key.application_key) == ("KEY_ID", "APP_KEY")
    with pytest.raises(AttributeError):
        key.application_key_id  # noqa: B018 - the point: the constructor's parameter name is not an attribute


def test_an_application_key_carries_its_expiry():
    assert application_key("KEY_ID", 1234.0).expiration_timestamp_millis == 1234.0
    assert application_key("KEY_ID").expiration_timestamp_millis is None


def test_a_bucket_has_the_id_it_was_given():
    assert bucket(stubbed_b2_api(), "bkt-1").id_ == "bkt-1"


def test_a_stubbed_api_serves_what_is_set_on_the_method_called():
    api = stubbed_b2_api()
    api.get_bucket_by_name.return_value = bucket(api, "bkt-1")
    api.create_key.return_value = full_application_key("NEW_ID", "NEW_KEY")

    assert api.get_bucket_by_name("homelab").id_ == "bkt-1"
    assert api.create_key(capabilities=["listKeys"], key_name="k").application_key == "NEW_KEY"
    api.create_key.assert_called_once_with(capabilities=["listKeys"], key_name="k")


def test_a_stubbed_api_stubs_the_session_delete_that_revokes_a_key():
    api = stubbed_b2_api()

    api.session.delete_key("OLD_ID")

    api.session.delete_key.assert_called_once_with("OLD_ID")


def test_a_stubbed_api_rejects_a_call_the_real_method_would():
    with pytest.raises(TypeError):
        stubbed_b2_api().create_key()


def test_the_b2_api_fixture_is_a_real_b2api_whose_network_calls_are_stubbed(b2_api):
    b2_api.authorize_account("production", "id", "key")

    assert isinstance(b2_api, B2Api)
    b2_api.authorize_account.assert_called_once_with("production", "id", "key")
