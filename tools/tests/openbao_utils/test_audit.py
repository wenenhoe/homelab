"""Unit tests for openbao_utils.audit's audit_oci/audit_local.

Run via `uv run pytest tools/tests/ -v`. Every provider/Vault call is
mocked; nothing here talks to a real tenancy, a real B2 account or a
real OpenBao.
audit.py's read_secret() reads through cloud_credentials'
own SECRET_OWNERS-mapped modules (Vault-backed) - AuditOciTests patches audit.read_secret directly rather
than seeding files, since it reads Vault, not a local file.
audit_local() is a different concern (scanning SECRETS_DIR for orphan
files left on disk), so AuditLocalTests still seeds real files there.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import create_autospec, patch

import pytest
from _oci_objects import customer_secret_key, customer_secret_keys_response
from _oci_objects import response as oci_response
from _responses import response
from _sessions import stubbed_session
from b2sdk.v2 import ApplicationKey
from oci.identity_domains.models import CustomerSecretKeys
from openbao_utils import audit


@pytest.fixture
def secret_values(monkeypatch) -> dict[str, str]:
    values: dict[str, str] = {}
    monkeypatch.setattr(audit, "read_secret", create_autospec(audit.read_secret, side_effect=lambda name: values.get(name)))
    return values


class TestAuditOci:
    @pytest.fixture(autouse=True)
    def oci_client_factory(self, identity_domains_client):
        with patch.object(audit, "oci_identity_domains_client", return_value=identity_domains_client, autospec=True) as factory:
            yield factory

    def test_no_scim_credentials_stops_after_the_header(self, oci_client_factory, identity_domains_client, secret_values, capsys):
        oci_client_factory.side_effect = SystemExit(1)

        audit.audit_oci()

        assert capsys.readouterr().out.strip() == "== OCI customer secret keys (write + read leaves) =="
        identity_domains_client.list_customer_secret_keys.assert_not_called()

    def test_leaf_without_cached_user_ocid_is_skipped(self, identity_domains_client, secret_values, capsys):
        # Neither _oci-leaf-user-ocid-write nor -read seeded.
        audit.audit_oci()

        printed = capsys.readouterr().out
        assert "write: no cached user OCID, skipping" in printed
        assert "read: no cached user OCID, skipping" in printed
        identity_domains_client.list_customer_secret_keys.assert_not_called()

    def test_active_key_matches_cached_scim_id_orphan_does_not(self, identity_domains_client, secret_values, capsys):
        secret_values["_oci-leaf-user-ocid-write"] = "ocid1.user.oc1..writeleaf"
        secret_values["oci-write-scim-id"] = "scim-active"
        identity_domains_client.list_customer_secret_keys.return_value = customer_secret_keys_response(
            customer_secret_key("scim-active", "ACCESS-ACTIVE", "unused", status="ACTIVE", created="2026-01-01T00:00:00Z"),
            customer_secret_key("scim-orphan", "ACCESS-ORPHAN", "unused", status="ACTIVE", created="2025-01-01T00:00:00Z"),
        )

        audit.audit_oci()

        printed = capsys.readouterr().out
        assert "write-leaf user has 2 customer secret key(s) (OCI allows max 2):" in printed
        assert "scim_id=scim-active  accessKey=ACCESS-ACTIVE  created=2026-01-01T00:00:00Z  status=ACTIVE  [ACTIVE (matches cache)]" in printed
        assert "scim_id=scim-orphan  accessKey=ACCESS-ORPHAN  created=2025-01-01T00:00:00Z  status=ACTIVE  [ORPHAN]" in printed
        assert "DELETE https://idcs-example.identity.oraclecloud.com/admin/v1/CustomerSecretKeys/scim-orphan" in printed
        assert "CustomerSecretKeys/scim-active" not in printed

    def test_filter_query_scoped_to_the_correct_leaf_user(self, identity_domains_client, secret_values):
        secret_values["_oci-leaf-user-ocid-write"] = "ocid1.user.oc1..writeleaf"
        identity_domains_client.list_customer_secret_keys.return_value = customer_secret_keys_response()

        audit.audit_oci()

        identity_domains_client.list_customer_secret_keys.assert_called_once_with(filter='user.ocid eq "ocid1.user.oc1..writeleaf"')

    def test_key_without_creation_metadata_or_status_is_listed_as_unknown(self, identity_domains_client, secret_values, capsys):
        secret_values["_oci-leaf-user-ocid-write"] = "ocid1.user.oc1..writeleaf"
        identity_domains_client.list_customer_secret_keys.return_value = customer_secret_keys_response(
            customer_secret_key("scim-bare", "ACCESS-BARE", "unused")
        )

        audit.audit_oci()

        assert "scim_id=scim-bare  accessKey=ACCESS-BARE  created=unknown  status=unknown  [ORPHAN]" in capsys.readouterr().out

    def test_response_without_a_resources_list_counts_as_no_keys(self, identity_domains_client, secret_values, capsys):
        secret_values["_oci-leaf-user-ocid-write"] = "ocid1.user.oc1..writeleaf"
        identity_domains_client.list_customer_secret_keys.return_value = oci_response(CustomerSecretKeys())

        audit.audit_oci()

        assert "write-leaf user has 0 customer secret key(s)" in capsys.readouterr().out


class TestCachedDispatch:
    """read_secret() itself: confirms it reads through the correct
    SECRET_OWNERS-mapped module rather than any local file."""

    def test_reads_via_the_names_own_module(self):
        with patch.object(audit._OWNER_BY_NAME["cloudflare-r2-account-id"], "read_secret", return_value="acct-123", autospec=True) as mock_read:
            assert audit.read_secret("cloudflare-r2-account-id") == "acct-123"
        mock_read.assert_called_once_with("cloudflare-r2-account-id")

    def test_unknown_name_raises_instead_of_silently_returning_none(self):
        with pytest.raises(KeyError):
            audit.read_secret("not-a-real-cloud-credentials-name")


class TestAuditLocal:
    @pytest.fixture(autouse=True)
    def env(self, tmp_path_factory, monkeypatch) -> SimpleNamespace:
        secrets = tmp_path_factory.mktemp("secrets")
        monkeypatch.setattr(audit, "SECRETS_DIR", secrets)

        # Deliberately a separate directory from SECRETS_DIR - audit_local()
        # scans every file under SECRETS_DIR, so a catalog file placed
        # inside it would incorrectly show up as its own orphan.
        catalog_dir = tmp_path_factory.mktemp("catalog")
        catalog_path = catalog_dir / "secret_catalog.yaml"
        catalog_path.write_text(
            "secret_catalog:\n"
            "  cloudflare-r2-write-access-key: { source: manual, store: controller_file }\n"
            "  cloudflare-r2-write-secret-key: { source: manual, store: controller_file }\n"
        )
        monkeypatch.setattr(audit, "CATALOG_PATH", catalog_path)
        return SimpleNamespace(secrets=secrets, seed=lambda name, value: (secrets / name).write_text(value))

    def test_r2_rotation_token_is_not_flagged_as_an_orphan(self, env):
        """Regression test: _rotation-key-cloudflare-r2-token was
        missing from KNOWN_INTERNAL_PATTERNS despite being a real,
        actively-used cache file (r2_rotation_token() reads it,
        cache_r2_rotation_token()/rotate_r2_rotation_token() write it) -
        a false-positive orphan that predates the OCI SCIM migration."""
        env.seed("_rotation-key-cloudflare-r2-token", "shh")
        env.seed("cloudflare-r2-write-access-key", "abc")
        env.seed("cloudflare-r2-write-secret-key", "def")

        with patch("sys.stdout", autospec=True) as mock_stdout:
            audit.audit_local()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        assert "not referenced by current config" not in printed
        assert "all belong to a permanent file-cache entry" in printed

    def test_genuinely_unreferenced_file_is_flagged(self, env):
        env.seed("cloudflare-r2-write-access-key", "abc")
        env.seed("cloudflare-r2-write-secret-key", "def")
        env.seed("some-leftover-from-a-naming-change", "stale")

        with patch("sys.stdout", autospec=True) as mock_stdout:
            audit.audit_local()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        assert "some-leftover-from-a-naming-change" in printed
        assert "1 file(s) not referenced" in printed

    def test_vault_backed_entry_with_a_stray_local_file_is_flagged_separately_from_an_orphan(self, env, tmp_path_factory, monkeypatch):
        """Regression test: a controller that predates the entry's move
        to Vault can have a stray, never-since-read local file for
        a catalog entry that has `store: openbao`. That's a distinct
        finding from a genuine orphan - the name IS known, it's just
        the wrong mechanism now."""
        catalog_dir = tmp_path_factory.mktemp("catalog")
        catalog_path = catalog_dir / "secret_catalog.yaml"
        catalog_path.write_text("secret_catalog:\n  lldap-jwt-secret: { source: hex, length: 32, store: openbao, scope: hosts/security }\n")
        monkeypatch.setattr(audit, "CATALOG_PATH", catalog_path)

        env.seed("lldap-jwt-secret", "stale-pre-vault-value")

        with patch("sys.stdout", autospec=True) as mock_stdout:
            audit.audit_local()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        assert "lldap-jwt-secret" in printed
        assert "scope: hosts/security" in printed
        assert "1 file(s) for a Vault-backed entry" in printed
        # Must not also be reported as a plain orphan - it's a known name.
        assert "not referenced by current config at all" not in printed

    def test_all_current_oci_scim_cache_keys_are_known(self, env):
        for name in [
            "_rotation-key-oci-domain-url",
            "_rotation-key-oci-client-id",
            "_rotation-key-oci-client-secret",
            "_rotation-key-oci-app-id",
            "_rotation-key-oci-created-at",
            "_oci-leaf-user-ocid-write",
            "_oci-leaf-user-ocid-read",
            "oci-write-scim-id",
            "oci-read-scim-id",
        ]:
            env.seed(name, "x")
        env.seed("cloudflare-r2-write-access-key", "abc")
        env.seed("cloudflare-r2-write-secret-key", "def")

        with patch("sys.stdout", autospec=True) as mock_stdout:
            audit.audit_local()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        assert "all belong to a permanent file-cache entry" in printed


def _b2_key(key_id: str, name: str = "some-key") -> ApplicationKey:
    return ApplicationKey(name, key_id, [], "acct")


class TestAuditB2:
    """audit_b2()'s active-key classification. Two cases need explicit
    handling: the openbao snapshot write leaf is cached in Vault and
    must be checked against it, and the break-glass readonly key
    (ADR 0017) can never match a cache lookup since it's never cached
    anywhere by design."""

    @pytest.fixture(autouse=True)
    def _stub_read_secret(self, secret_values):
        secret_values.update(
            {
                "_rotation-key-backblaze-b2-key-id": "rotation-key-id",
                "backblaze-b2-write-access-key": "write-key-id",
                "backblaze-b2-read-access-key": "read-key-id",
                "backblaze-b2-openbao-snapshot-write-access-key": "snapshot-write-key-id",
            }
        )

    @pytest.fixture
    def listed_keys(self, capsys):
        """Runs audit_b2() against an account holding the given keys and returns what it printed."""

        def run(*keys: ApplicationKey) -> str:
            with (
                patch.object(audit, "b2_rotation_api", autospec=True),
                patch.object(audit, "b2_list_keys", return_value=list(keys), autospec=True),
            ):
                audit.audit_b2()
            return capsys.readouterr().out

        return run

    def test_cached_leaf_and_rotation_keys_are_active(self, listed_keys):
        printed = listed_keys(_b2_key("write-key-id"), _b2_key("read-key-id"), _b2_key("rotation-key-id"))

        assert "3 key(s) on the account:" in printed
        assert "write-key-id  name=some-key  [ACTIVE (write)]" in printed
        assert "read-key-id  name=some-key  [ACTIVE (read)]" in printed
        assert "rotation-key-id  name=some-key  [ACTIVE (rotation key)]" in printed
        assert "ORPHAN" not in printed

    def test_openbao_snapshot_write_leaf_is_active_not_orphan(self, listed_keys):
        printed = listed_keys(_b2_key("snapshot-write-key-id", "openbao-snapshot-write"))

        assert "ACTIVE (openbao snapshot write leaf)" in printed
        assert "ORPHAN" not in printed

    def test_openbao_snapshot_readonly_is_active_matched_by_name(self, listed_keys):
        printed = listed_keys(_b2_key("some-other-id", "openbao-snapshot-readonly"))

        assert "ACTIVE (break-glass restore key" in printed
        assert "ORPHAN" not in printed

    def test_genuinely_unknown_key_is_still_flagged_orphan(self, listed_keys):
        printed = listed_keys(_b2_key("mystery-id", "some-leftover-key"))

        assert "mystery-id  name=some-leftover-key  [ORPHAN]" in printed
        assert "delete: b2_delete_key with applicationKeyId=mystery-id" in printed

    def test_no_cached_rotation_key_stops_after_the_header_without_listing(self, capsys):
        # b2_rotation_api() exits after printing what is missing when the rotation key isn't cached.
        with (
            patch.object(audit, "b2_rotation_api", side_effect=SystemExit(1), autospec=True),
            patch.object(audit, "b2_list_keys", autospec=True) as mock_list_keys,
        ):
            audit.audit_b2()

        assert capsys.readouterr().out.strip() == "== B2 application keys (via rotation key) =="
        mock_list_keys.assert_not_called()


def _run_r2_with_tokens(tokens):
    resp = response(200, {"success": True, "result": tokens})
    session = stubbed_session()
    session.get.return_value = resp
    with (
        patch("openbao_utils.audit.requests.Session", autospec=True, return_value=session),
        patch("openbao_utils.audit.getpass.getpass", return_value="admin-token", autospec=True),
        patch("sys.stdout", autospec=True) as mock_stdout,
    ):
        audit.audit_r2()
    return "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)


class TestAuditR2:
    """audit_r2()'s active-token classification - same two bugs as
    AuditB2Tests, plus a third: the token-name filter excluded both
    openbao-snapshot tokens entirely (neither matches the
    homelab-cloud-sync-r2- prefix), so they never appeared in the audit
    at all, orphan or not."""

    @pytest.fixture(autouse=True)
    def _stub_read_secret(self, secret_values):
        secret_values.update(
            {
                "cloudflare-r2-account-id": "acct-123",
                "cloudflare-r2-write-access-key": "write-token-id",
                "cloudflare-r2-read-access-key": "read-token-id",
                "cloudflare-r2-openbao-snapshot-write-access-key": "snapshot-write-token-id",
            }
        )

    def test_openbao_snapshot_write_token_is_included_and_active(self):
        printed = _run_r2_with_tokens([{"id": "snapshot-write-token-id", "name": "openbao-snapshot-write", "status": "active"}])
        assert "ACTIVE (openbao snapshot write leaf)" in printed
        assert "ORPHAN" not in printed

    def test_openbao_snapshot_readonly_token_is_included_and_active(self):
        printed = _run_r2_with_tokens([{"id": "some-other-id", "name": "openbao-snapshot-readonly", "status": "active"}])
        assert "ACTIVE (break-glass restore key" in printed
        assert "ORPHAN" not in printed

    def test_token_outside_known_naming_is_excluded_from_the_count_entirely(self):
        # Not a regression target of this fix - documents the existing
        # filter's own behavior so a future change to it is deliberate.
        printed = _run_r2_with_tokens([{"id": "unrelated-id", "name": "some-unrelated-token", "status": "active"}])
        assert "0 homelab-cloud-sync-r2-*/openbao-snapshot-* token(s)" in printed
