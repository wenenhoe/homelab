"""Unit tests for cloud_credentials.rotation_keys.r2.

Run via `uv run pytest tools/tests/ -v`. getpass is always mocked;
nothing here actually blocks on stdin.
"""

from __future__ import annotations

from unittest.mock import patch

from cloud_credentials.rotation_keys import r2 as rotation_r2


class TestCacheR2RotationToken:
    @patch.object(rotation_r2, "_prompt_r2_admin_token", return_value="NEW_TOKEN", autospec=True)
    def test_prompts_and_caches_on_first_run(self, mock_prompt, rotation_vault):
        rotation_r2.cache_r2_rotation_token()

        mock_prompt.assert_called_once()
        assert rotation_vault.get("_rotation-key-cloudflare-r2-token") == "NEW_TOKEN"

    @patch.object(rotation_r2, "_prompt_r2_admin_token", autospec=True)
    def test_skips_entirely_when_already_cached(self, mock_prompt, rotation_vault):
        rotation_vault.seed("_rotation-key-cloudflare-r2-token", "EXISTING_TOKEN")

        rotation_r2.cache_r2_rotation_token()

        # The whole point of the cache check: never re-prompt once a
        # token already exists — matches create_b2_rotation_key's and
        # create_oci_rotation_key's own idempotent shape.
        mock_prompt.assert_not_called()
        assert rotation_vault.get("_rotation-key-cloudflare-r2-token") == "EXISTING_TOKEN"


class TestRotateR2RotationToken:
    @patch.object(rotation_r2, "_prompt_r2_admin_token", return_value="ROLLED_TOKEN", autospec=True)
    def test_overwrites_existing_cached_token_unconditionally(self, mock_prompt, rotation_vault):
        rotation_vault.seed("_rotation-key-cloudflare-r2-token", "OLD_TOKEN")

        ok = rotation_r2.rotate_r2_rotation_token()

        # This is the actual fix for the real incident: rolling the
        # Custom Token in the Console already revoked OLD_TOKEN before
        # this ever runs — there's no "verify old still works" step to
        # gate on the way B2/OCI's rotate has, so this must always
        # prompt and overwrite, never skip because something's cached.
        assert ok
        mock_prompt.assert_called_once()
        assert rotation_vault.get("_rotation-key-cloudflare-r2-token") == "ROLLED_TOKEN"

    @patch.object(rotation_r2, "_prompt_r2_admin_token", return_value="FIRST_TOKEN", autospec=True)
    def test_works_even_with_nothing_cached_yet(self, mock_prompt, rotation_vault):
        ok = rotation_r2.rotate_r2_rotation_token()

        assert ok
        assert rotation_vault.get("_rotation-key-cloudflare-r2-token") == "FIRST_TOKEN"
