"""Real b2sdk objects for the cloud_credentials tests.

A key, a bucket and an api are the library's own, so a test reads the
fields the real class has (a FullApplicationKey keeps its id as `id_`, not
`application_key_id`) and a call the real signature would reject fails.
The api is a real `B2Api` over an in-memory account whose network calls
are autospec'd stand-ins; a test sets `.return_value` on the one the code
under test is expected to call.
"""

from __future__ import annotations

from unittest.mock import create_autospec

from b2sdk.v2 import ApplicationKey, B2Api, Bucket, FullApplicationKey, InMemoryAccountInfo

_API_METHODS = ("authorize_account", "get_bucket_by_name", "get_bucket_by_id", "list_buckets", "create_key", "delete_key", "list_keys")


def stubbed_b2_api() -> B2Api:
    api = B2Api(InMemoryAccountInfo())
    for name in _API_METHODS:
        setattr(api, name, create_autospec(getattr(api, name)))
    api.session.delete_key = create_autospec(api.session.delete_key)
    return api


def full_application_key(key_id: str, secret: str, name: str = "key") -> FullApplicationKey:
    return FullApplicationKey(key_name=name, application_key_id=key_id, application_key=secret, capabilities=[], account_id="acct")


def application_key(key_id: str, expiration_ms: float | None = None) -> ApplicationKey:
    return ApplicationKey("key", key_id, [], "acct", expiration_timestamp_millis=expiration_ms)


def bucket(api: B2Api, bucket_id: str = "bkt", name: str = "bucket-name") -> Bucket:
    return Bucket(api, bucket_id, name=name)
