"""Unit tests for cloud_credentials.rotation_keys.oci_iam.

Run via `uv run pytest tools/tests/ -v`. Every HTTP call is stubbed;
nothing here talks to a real tenancy.
"""

from __future__ import annotations

from unittest.mock import create_autospec

import pytest
import requests
from _responses import response
from cloud_credentials.rotation_keys import oci_iam

ENDPOINT = "https://identity.example"
TENANCY = "ocid1.tenancy.oc1..t"


def _post(path: str, body: dict) -> dict:
    """The signature of the `post` closure create_oci_rotation_key hands these helpers."""
    raise NotImplementedError


@pytest.fixture
def post():
    return create_autospec(_post)


def _http_error(status_code: int) -> requests.HTTPError:
    """The error `raise_for_status()` raises for this status, message included."""
    with pytest.raises(requests.HTTPError) as exc:
        response(status_code).raise_for_status()
    return exc.value


class TestUserEmail:
    @pytest.mark.parametrize(
        ("admin_email", "expected"),
        [
            pytest.param("you@example.com", "you+homelab-cloud-sync-write@example.com", id="plain-mailbox"),
            pytest.param("you+ops@example.com", "you+ops+homelab-cloud-sync-write@example.com", id="mailbox-already-tagged"),
        ],
    )
    def test_tags_the_local_part_and_keeps_the_domain(self, admin_email, expected):
        assert oci_iam.user_email(admin_email, "homelab-cloud-sync-write") == expected


class TestOciLookupOne:
    def test_returns_the_single_match_from_the_list(self, http_session):
        http_session.get.return_value = response(json_body=[{"id": "ocid1.group.oc1..g", "name": "g1"}])

        found = oci_iam.oci_lookup_one(http_session, ENDPOINT, TENANCY, "groups", "g1")

        assert found == {"id": "ocid1.group.oc1..g", "name": "g1"}
        http_session.get.assert_called_once_with(f"{ENDPOINT}/20160918/groups", params={"compartmentId": TENANCY, "name": "g1"})

    @pytest.mark.parametrize(
        ("body", "found"),
        [
            pytest.param([], 0, id="none"),
            pytest.param([{"id": "a"}, {"id": "b"}], 2, id="several"),
        ],
    )
    def test_exits_unless_exactly_one_match(self, http_session, capsys, body, found):
        http_session.get.return_value = response(json_body=body)

        with pytest.raises(SystemExit) as exc:
            oci_iam.oci_lookup_one(http_session, ENDPOINT, TENANCY, "policies", "p1")

        assert exc.value.code == 1
        assert f"oci: expected exactly one existing policie named p1, found {found}" in capsys.readouterr().err

    def test_raises_on_an_http_error_instead_of_reading_the_body(self, http_session):
        http_session.get.return_value = response(500, json_body=[{"id": "ocid1.group.oc1..g"}])

        with pytest.raises(requests.HTTPError, match="500"):
            oci_iam.oci_lookup_one(http_session, ENDPOINT, TENANCY, "groups", "g1")


class TestOciGetOrCreateUser:
    def test_creates_the_user_with_a_tagged_email(self, http_session, post):
        post.return_value = {"id": "ocid1.user.oc1..new"}

        user = oci_iam.oci_get_or_create_user(http_session, ENDPOINT, post, TENANCY, "svc", "a service", "you@example.com")

        assert user == {"id": "ocid1.user.oc1..new"}
        post.assert_called_once_with("/20160918/users", {"compartmentId": TENANCY, "name": "svc", "description": "a service", "email": "you+svc@example.com"})
        http_session.get.assert_not_called()

    def test_looks_up_the_existing_user_on_409(self, http_session, post, capsys):
        post.side_effect = _http_error(409)
        http_session.get.return_value = response(json_body=[{"id": "ocid1.user.oc1..old"}])

        user = oci_iam.oci_get_or_create_user(http_session, ENDPOINT, post, TENANCY, "svc", "a service", "you@example.com")

        assert user == {"id": "ocid1.user.oc1..old"}
        http_session.get.assert_called_once_with(f"{ENDPOINT}/20160918/users", params={"compartmentId": TENANCY, "name": "svc"})
        assert "oci: user svc already exists" in capsys.readouterr().err

    def test_reraises_any_other_http_error_without_a_lookup(self, http_session, post):
        post.side_effect = _http_error(403)

        with pytest.raises(requests.HTTPError, match="403"):
            oci_iam.oci_get_or_create_user(http_session, ENDPOINT, post, TENANCY, "svc", "a service", "you@example.com")

        http_session.get.assert_not_called()


class TestOciGetOrCreateGroup:
    def test_creates_the_group(self, http_session, post):
        post.return_value = {"id": "ocid1.group.oc1..new"}

        group = oci_iam.oci_get_or_create_group(http_session, ENDPOINT, post, TENANCY, "grp", "a group")

        assert group == {"id": "ocid1.group.oc1..new"}
        post.assert_called_once_with("/20160918/groups", {"compartmentId": TENANCY, "name": "grp", "description": "a group"})
        http_session.get.assert_not_called()

    def test_looks_up_the_existing_group_on_409(self, http_session, post, capsys):
        post.side_effect = _http_error(409)
        http_session.get.return_value = response(json_body=[{"id": "ocid1.group.oc1..old"}])

        group = oci_iam.oci_get_or_create_group(http_session, ENDPOINT, post, TENANCY, "grp", "a group")

        assert group == {"id": "ocid1.group.oc1..old"}
        http_session.get.assert_called_once_with(f"{ENDPOINT}/20160918/groups", params={"compartmentId": TENANCY, "name": "grp"})
        assert "oci: group grp already exists" in capsys.readouterr().err

    def test_reraises_any_other_http_error_without_a_lookup(self, http_session, post):
        post.side_effect = _http_error(500)

        with pytest.raises(requests.HTTPError, match="500"):
            oci_iam.oci_get_or_create_group(http_session, ENDPOINT, post, TENANCY, "grp", "a group")

        http_session.get.assert_not_called()
