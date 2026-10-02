"""Real OCI SDK objects for the cloud_credentials tests.

The client is the `IdentityDomainsClient` the repo's own factory builds
(`identity_domains_client_for_token`), so `client.base_client.endpoint`,
which the code reads, is real. Every service call funnels through
`base_client.call_api`, which is an autospec'd stand-in, and the calls the
code makes are stubbed on top; a test sets `.return_value` on the one it
expects to be called. The SDK's service methods take `**kwargs`, so what
the code sends is pinned by the test's assertion on the call.

Keys, apps and responses are the SDK's own model classes.
"""

from __future__ import annotations

import warnings
from unittest.mock import create_autospec

import oci
from cloud_credentials.rotation_keys.oci_scim import identity_domains_client_for_token
from oci.identity_domains import IdentityDomainsClient
from oci.identity_domains.models import App, Apps, CustomerSecretKey

_CLIENT_METHODS = ("list_apps", "create_customer_secret_key", "delete_customer_secret_key", "list_customer_secret_keys", "get_customer_secret_key")


def stubbed_identity_domains_client() -> IdentityDomainsClient:
    with warnings.catch_warnings():
        # Building any SDK client decorates it with `circuitbreaker`, which still calls
        # asyncio.iscoroutinefunction (removed in Python 3.16). Only that one warning, only here.
        warnings.filterwarnings("ignore", message=r"'asyncio\.iscoroutinefunction' is deprecated", category=DeprecationWarning)
        client = identity_domains_client_for_token("https://idcs-example.identity.oraclecloud.com", "tok")
    client.base_client.call_api = create_autospec(client.base_client.call_api)
    for name in _CLIENT_METHODS:
        setattr(client, name, create_autospec(getattr(client, name)))
    return client


def response(data: object, status: int = 200) -> oci.response.Response:
    return oci.response.Response(status, {}, data, None)


def customer_secret_key(scim_id: str, access_key: str, secret_key: str) -> CustomerSecretKey:
    return CustomerSecretKey(id=scim_id, access_key=access_key, secret_key=secret_key)


def apps_response(*app_ids: str) -> oci.response.Response:
    return response(Apps(resources=[App(id=app_id) for app_id in app_ids]))
