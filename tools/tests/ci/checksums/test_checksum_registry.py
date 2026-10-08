"""Tests for ci.checksums.registry.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re

import pytest
from ci.checksums import registry
from ci.checksums.registry import ENTRIES, Attested, Listed, Location, Signed, Tier, Unchecked

WHERE = {"pin": Location("defaults.yaml", "tool_sha256"), "version": Location("defaults.yaml", "tool_version")}
SIGNED = {
    "name": "tool",
    "file": "tool-{version}.zip",
    "manifest_url": "https://example.invalid/{version}/SHA256SUMS",
    "fingerprint": "A" * 40,
    "key": "keys/tool.asc",
}


class TestSigned:
    def test_a_complete_entry_is_signed_and_a_signature_url_is_optional(self):
        entry = Signed(**WHERE, **SIGNED)
        assert (entry.tier, entry.signature_url) == (Tier.SIGNED, None)
        assert Signed(**WHERE, **SIGNED, signature_url="https://example.invalid/{version}/SHA256SUMS.sig").signature_url

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            pytest.param({"fingerprint": "a" * 40}, "40 upper-case hex", id="lower-case-fingerprint"),
            pytest.param({"fingerprint": "A" * 39}, "40 upper-case hex", id="short-fingerprint"),
            pytest.param({"manifest_url": "http://example.invalid/SHA256SUMS"}, "manifest_url must be an https URL", id="plain-http-manifest"),
            pytest.param({"signature_url": "ftp://example.invalid/sig"}, "signature_url must be an https URL", id="non-https-signature"),
            pytest.param({"manifest_url": "https://example.invalid/{os}/SHA256SUMS"}, r"manifest_url may only use \{version\}", id="other-placeholder"),
            pytest.param({"file": "{version.__class__}"}, r"file may only use \{version\}", id="attribute-lookup"),
            pytest.param({"file": "./tool.zip"}, "file must be a bare name", id="dot-slash-file"),
            pytest.param({"file": "/tool.zip"}, "file must be a bare name", id="rooted-file"),
            pytest.param({"file": "tool v1.zip"}, "file must be a bare name", id="file-with-a-space"),
        ],
    )
    def test_an_entry_that_would_weaken_the_check_is_refused(self, change, message):
        with pytest.raises(ValueError, match=message):
            Signed(**WHERE, **{**SIGNED, **change})

    def test_a_signed_entry_without_a_key_or_fingerprint_cannot_be_built(self):
        for missing in ("key", "fingerprint"):
            with pytest.raises(TypeError, match=missing):
                Signed(**WHERE, **{k: v for k, v in SIGNED.items() if k != missing})


ATTESTED = {"name": "tool", "artifact_url": "https://example.invalid/{version}/tool.tar.gz", "repository": "owner/tool"}


class TestAttested:
    def test_a_complete_entry_is_attested(self):
        assert Attested(**WHERE, **ATTESTED).tier is Tier.ATTESTED

    def test_an_entry_with_no_repository_cannot_be_built(self):
        with pytest.raises(TypeError, match="repository"):
            Attested(**WHERE, name="tool", artifact_url=ATTESTED["artifact_url"])

    @pytest.mark.parametrize(
        "repository",
        [pytest.param("tool", id="no-owner"), pytest.param("a/b/c", id="too-deep"), pytest.param("a b/c", id="space"), pytest.param("", id="empty")],
    )
    def test_a_repository_that_is_not_owner_slash_name_is_refused(self, repository):
        with pytest.raises(ValueError, match="owner/name"):
            Attested(**WHERE, **{**ATTESTED, "repository": repository})

    def test_an_artifact_url_must_be_https(self):
        with pytest.raises(ValueError, match="artifact_url must be an https URL"):
            Attested(**WHERE, **{**ATTESTED, "artifact_url": "http://example.invalid/tool.tar.gz"})


class TestListedAndUnchecked:
    def test_a_listed_entry_needs_a_manifest_and_a_file(self):
        entry = Listed(**WHERE, name="tool", file="tool.zip", manifest_url="https://example.invalid/SHA256SUMS")
        assert entry.tier is Tier.LISTED
        with pytest.raises(TypeError, match="manifest_url"):
            Listed(**WHERE, name="tool", file="tool.zip")

    def test_a_listed_entry_cannot_claim_a_key(self):
        with pytest.raises(TypeError, match="fingerprint"):
            Listed(**WHERE, name="tool", file="tool.zip", manifest_url="https://example.invalid/SHA256SUMS", fingerprint="A" * 40)

    def test_an_unchecked_entry_says_why(self):
        assert Unchecked(**WHERE, name="tool", reason="no manifest is published").tier is Tier.NONE
        with pytest.raises(ValueError, match="say why"):
            Unchecked(**WHERE, name="tool", reason="  ")


class TestRealRegistry:
    def test_every_entry_is_named_once(self):
        names = [entry.name for entry in ENTRIES]
        assert len(names) == len(set(names))

    def test_each_artifact_has_the_tier_its_publisher_allows(self):
        assert {entry.name: entry.tier for entry in ENTRIES} == {
            "uv": Tier.ATTESTED,
            "rclone": Tier.SIGNED,
            "openbao-cli": Tier.SIGNED,
            "coderabbit-cli": Tier.LISTED,
        }

    def test_every_pin_is_a_different_variable(self):
        pins = [(entry.pin.path, entry.pin.name) for entry in ENTRIES]
        assert len(pins) == len(set(pins))

    def test_the_signed_entries_have_a_key_file_and_a_fingerprint_each_of_their_own(self, subtests):
        signed = [entry for entry in ENTRIES if isinstance(entry, Signed)]
        assert len({entry.key for entry in signed}) == len({entry.fingerprint for entry in signed}) == len(signed)
        for entry in signed:
            with subtests.test(entry=entry.name):
                assert re.fullmatch(rf"{re.escape(registry.KEYS)}/[a-z-]+\.asc", entry.key)

    def test_the_attested_artifact_is_attested_for_the_repository_that_builds_it(self):
        uv = next(entry for entry in ENTRIES if entry.name == "uv")
        assert isinstance(uv, Attested)
        assert uv.repository == "astral-sh/uv"
        assert "github.com/astral-sh/uv/" in uv.artifact_url
