"""Unit tests for openbao_utils.audit's audit_oci/audit_local.

Run via `uv run pytest tools/tests/ -v`. Every SCIM/Vault call is
mocked; nothing here talks to a real tenancy or a real OpenBao.
audit.py's cached() reads through cloud_credentials'
own LEGACY_CACHE_KEYS-mapped modules (Vault-backed, since Track A
stage 5) - AuditOciTests patches audit.cached directly rather
than seeding files, since there's no longer a local file it reads.
audit_local() is a different concern (scanning SECRETS_DIR for orphan
files left on disk), so AuditLocalTests still seeds real files there.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from _responses import response
from _sessions import stubbed_session
from openbao_utils import audit


@pytest.fixture
def cached_values(monkeypatch) -> dict[str, str]:
    values: dict[str, str] = {}
    monkeypatch.setattr(audit, "cached", MagicMock(side_effect=lambda name: values.get(name)))
    return values


class TestAuditOci:
    @patch("cloud_credentials.rotation_keys.oci_scim.oci_scim_session", side_effect=SystemExit(1))
    def test_no_scim_credentials_stops_after_the_header(self, mock_session, cached_values, capsys):
        audit.audit_oci()

        assert capsys.readouterr().out.strip() == "== OCI customer secret keys (write + read leaves) =="

    @patch("cloud_credentials.rotation_keys.oci_scim.oci_scim_session")
    def test_leaf_without_cached_user_ocid_is_skipped(self, mock_session, cached_values):
        # Neither _oci-leaf-user-ocid-write nor -read seeded.
        session = stubbed_session()
        mock_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        with patch("sys.stdout") as mock_stdout:
            audit.audit_oci()

        session.get.assert_not_called()
        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        assert "no cached user OCID, skipping" in printed

    @patch("cloud_credentials.rotation_keys.oci_scim.oci_scim_session")
    def test_active_key_matches_cached_scim_id_orphan_does_not(self, mock_session, cached_values):
        cached_values["_oci-leaf-user-ocid-write"] = "ocid1.user.oc1..writeleaf"
        cached_values["oci-write-scim-id"] = "scim-active"
        session = stubbed_session()

        def get_side_effect(url, params=None):
            if "user.ocid eq" in params.get("filter", ""):
                return response(
                    200,
                    {
                        "Resources": [
                            {"id": "scim-active", "accessKey": "ACCESS-ACTIVE", "status": "ACTIVE", "meta": {"created": "2026-01-01T00:00:00Z"}},
                            {"id": "scim-orphan", "accessKey": "ACCESS-ORPHAN", "status": "ACTIVE", "meta": {"created": "2025-01-01T00:00:00Z"}},
                        ]
                    },
                )
            return response(200, {"Resources": []})

        session.get.side_effect = get_side_effect
        mock_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        with patch("sys.stdout") as mock_stdout:
            audit.audit_oci()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        assert "scim_id=scim-active" in printed
        assert "ACTIVE (matches cache)" in printed
        assert "scim_id=scim-orphan" in printed
        assert "ORPHAN" in printed
        assert "DELETE https://idcs-example.identity.oraclecloud.com/admin/v1/CustomerSecretKeys/scim-orphan" in printed

    @patch("cloud_credentials.rotation_keys.oci_scim.oci_scim_session")
    def test_filter_query_scoped_to_the_correct_leaf_user(self, mock_session, cached_values):
        cached_values["_oci-leaf-user-ocid-write"] = "ocid1.user.oc1..writeleaf"
        session = stubbed_session()
        session.get.return_value = response(200, {"Resources": []})
        mock_session.return_value = (session, "https://idcs-example.identity.oraclecloud.com")

        audit.audit_oci()

        sent_filter = session.get.call_args.kwargs["params"]["filter"]
        assert "ocid1.user.oc1..writeleaf" in sent_filter


class TestCachedDispatch:
    """cached() itself: confirms it reads through the correct
    LEGACY_CACHE_KEYS-mapped module rather than any local file."""

    def test_reads_via_the_names_own_module(self):
        with patch.object(audit._CACHE_MODULE_BY_NAME["cloudflare-r2-account-id"], "read_cache", return_value="acct-123") as mock_read:
            assert audit.cached("cloudflare-r2-account-id") == "acct-123"
        mock_read.assert_called_once_with("cloudflare-r2-account-id")

    def test_unknown_name_raises_instead_of_silently_returning_none(self):
        with pytest.raises(KeyError):
            audit.cached("not-a-real-cloud-credentials-name")


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

        with patch("sys.stdout") as mock_stdout:
            audit.audit_local()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        assert "not referenced by current config" not in printed
        assert "all belong to a permanent file-cache entry" in printed

    def test_genuinely_unreferenced_file_is_flagged(self, env):
        env.seed("cloudflare-r2-write-access-key", "abc")
        env.seed("cloudflare-r2-write-secret-key", "def")
        env.seed("some-leftover-from-a-naming-change", "stale")

        with patch("sys.stdout") as mock_stdout:
            audit.audit_local()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        assert "some-leftover-from-a-naming-change" in printed
        assert "1 file(s) not referenced" in printed

    def test_vault_backed_entry_with_a_stray_local_file_is_flagged_separately_from_an_orphan(self, env, tmp_path_factory, monkeypatch):
        """Regression test: a controller that predates the entry's move
        to Vault (Track A stage 4 for most entries, stage 5/6 for cloud
        credentials) can have a stray, never-since-read local file for
        a catalog entry that has `store: openbao`. That's a distinct
        finding from a genuine orphan - the name IS known, it's just
        the wrong mechanism now - found via the stage 6 cutover drill
        surfacing exactly this on a real controller."""
        catalog_dir = tmp_path_factory.mktemp("catalog")
        catalog_path = catalog_dir / "secret_catalog.yaml"
        catalog_path.write_text("secret_catalog:\n  lldap-jwt-secret: { source: hex, length: 32, store: openbao, scope: hosts/security }\n")
        monkeypatch.setattr(audit, "CATALOG_PATH", catalog_path)

        env.seed("lldap-jwt-secret", "stale-pre-vault-value")

        with patch("sys.stdout") as mock_stdout:
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

        with patch("sys.stdout") as mock_stdout:
            audit.audit_local()

        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        assert "all belong to a permanent file-cache entry" in printed


def _mock_b2_session(keys):
    auth_resp = response(200, {"authorizationToken": "tok", "apiUrl": "https://api.example.com", "accountId": "acct"})
    list_resp = response(200, {"keys": keys})
    session = stubbed_session()
    session.get.return_value = list_resp
    return auth_resp, session


class TestAuditB2:
    """audit_b2()'s active-key classification. Regression coverage for
    two real bugs found running audit.py --provider all against
    a live account (Track A stage 6's cutover drill): the openbao
    snapshot write leaf was cached in Vault but never checked against,
    and the break-glass readonly key (ADR 0017) can never match a cache
    lookup since it's never cached anywhere by design."""

    @pytest.fixture(autouse=True)
    def _cached(self, cached_values):
        cached_values.update(
            {
                "_rotation-key-backblaze-b2-key-id": "rotation-key-id",
                "_rotation-key-backblaze-b2-application-key": "rotation-app-key",
                "backblaze-b2-write-access-key": "write-key-id",
                "backblaze-b2-read-access-key": "read-key-id",
                "backblaze-b2-openbao-snapshot-write-access-key": "snapshot-write-key-id",
            }
        )

    def test_openbao_snapshot_write_leaf_is_active_not_orphan(self):
        auth_resp, session = _mock_b2_session([{"applicationKeyId": "snapshot-write-key-id", "keyName": "openbao-snapshot-write"}])
        with (
            patch("openbao_utils.audit.requests.get", return_value=auth_resp),
            patch("openbao_utils.audit.requests.Session", autospec=True, return_value=session),
            patch("sys.stdout") as mock_stdout,
        ):
            audit.audit_b2()
        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        assert "ACTIVE (openbao snapshot write leaf)" in printed
        assert "ORPHAN" not in printed

    def test_openbao_snapshot_readonly_is_active_matched_by_name(self):
        auth_resp, session = _mock_b2_session([{"applicationKeyId": "some-other-id", "keyName": "openbao-snapshot-readonly"}])
        with (
            patch("openbao_utils.audit.requests.get", return_value=auth_resp),
            patch("openbao_utils.audit.requests.Session", autospec=True, return_value=session),
            patch("sys.stdout") as mock_stdout,
        ):
            audit.audit_b2()
        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        assert "ACTIVE (break-glass restore key" in printed
        assert "ORPHAN" not in printed

    def test_genuinely_unknown_key_is_still_flagged_orphan(self):
        auth_resp, session = _mock_b2_session([{"applicationKeyId": "mystery-id", "keyName": "some-leftover-key"}])
        with (
            patch("openbao_utils.audit.requests.get", return_value=auth_resp),
            patch("openbao_utils.audit.requests.Session", autospec=True, return_value=session),
            patch("sys.stdout") as mock_stdout,
        ):
            audit.audit_b2()
        printed = "".join(call.args[0] for call in mock_stdout.write.call_args_list if call.args)
        assert "mystery-id" in printed
        assert "ORPHAN" in printed


def _run_r2_with_tokens(tokens):
    resp = response(200, {"success": True, "result": tokens})
    session = stubbed_session()
    session.get.return_value = resp
    with (
        patch("openbao_utils.audit.requests.Session", autospec=True, return_value=session),
        patch("openbao_utils.audit.getpass.getpass", return_value="admin-token"),
        patch("sys.stdout") as mock_stdout,
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
    def _cached(self, cached_values):
        cached_values.update(
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
