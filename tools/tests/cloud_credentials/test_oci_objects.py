"""Tests for the OCI SDK helpers in _oci_objects.py and the identity_domains_client fixture."""

from __future__ import annotations

import pytest
from _oci_objects import apps_response, customer_secret_key, response, stubbed_identity_domains_client
from oci.identity_domains import IdentityDomainsClient


def test_a_customer_secret_key_carries_its_scim_id_and_both_halves():
    key = customer_secret_key("SCIM_ID", "ACCESS", "SECRET")

    assert (key.id, key.access_key, key.secret_key) == ("SCIM_ID", "ACCESS", "SECRET")


def test_a_response_serves_its_data_and_status():
    resp = response(customer_secret_key("SCIM_ID", "ACCESS", "SECRET"), status=201)

    assert resp.status == 201
    assert resp.data.access_key == "ACCESS"


def test_an_apps_response_lists_the_given_app_ids_and_none_for_an_empty_one():
    assert [app.id for app in apps_response("app-1", "app-2").data.resources] == ["app-1", "app-2"]
    assert apps_response().data.resources == []


def test_a_stubbed_client_keeps_the_endpoint_the_code_reads_in_an_error_message():
    assert stubbed_identity_domains_client().base_client.endpoint == "https://idcs-example.identity.oraclecloud.com"


def test_a_stubbed_client_serves_what_is_set_on_the_method_called():
    client = stubbed_identity_domains_client()
    client.list_apps.return_value = apps_response("app-1")

    assert client.list_apps(filter='displayName eq "x"').data.resources[0].id == "app-1"
    client.list_apps.assert_called_once_with(filter='displayName eq "x"')


def test_a_stubbed_client_cannot_reach_the_network_through_an_unstubbed_method():
    client = stubbed_identity_domains_client()

    client.list_users()

    client.base_client.call_api.assert_called_once()


def test_a_stubbed_client_rejects_a_call_the_real_method_would():
    with pytest.raises(TypeError):
        stubbed_identity_domains_client().delete_customer_secret_key()


def test_the_identity_domains_client_fixture_is_a_real_client(identity_domains_client):
    assert isinstance(identity_domains_client, IdentityDomainsClient)
