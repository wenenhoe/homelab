"""Tests for ci.provenance.registry.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re

import pytest
from ci.images import remote
from ci.provenance import pins, registry
from ci.provenance.registry import ENTRIES, Attested, Signed, Tier, Unsigned

ISSUER = "https://token.actions.githubusercontent.com"
IDENTITY = "https://github.com/owner/tool/.github/workflows/release.yml@refs/tags/v1.0.0"
PATTERN = r"^https://github\.com/owner/tool/\.github/workflows/release\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$"
KEY = f"{registry.KEYS}/tool.pub"


class TestImageName:
    @pytest.mark.parametrize(
        ("image", "key"),
        [
            pytest.param("ghcr.io/owner/tool", ("ghcr.io", "owner/tool"), id="ghcr"),
            pytest.param("owner/tool", ("registry-1.docker.io", "owner/tool"), id="docker-hub-namespace"),
            pytest.param("ubuntu", ("registry-1.docker.io", "library/ubuntu"), id="docker-hub-official-image"),
            pytest.param("ghcr.io/owner/group/tool", ("ghcr.io", "owner/group/tool"), id="nested-repository"),
        ],
    )
    def test_an_image_is_keyed_the_way_a_reference_to_it_is_read(self, image, key):
        assert Unsigned(image=image, reason="nothing offered").registry_key == key

    @pytest.mark.parametrize(
        "image",
        [
            pytest.param("ghcr.io/owner/tool:1.0", id="tag"),
            pytest.param("ghcr.io/owner/tool@sha256:" + "a" * 64, id="digest"),
            pytest.param("ghcr.io/owner/tool:1.0@sha256:" + "a" * 64, id="tag-and-digest"),
            pytest.param("owner/tool:latest", id="docker-hub-tag"),
            pytest.param("ghcr.io/owner/tool/", id="trailing-slash"),
            pytest.param("ghcr.io/owner/to ol", id="space"),
            pytest.param("", id="empty"),
        ],
    )
    def test_a_name_that_is_not_a_bare_repository_is_refused(self, image):
        with pytest.raises(ValueError, match=r"without a tag or a digest|not an image reference"):
            Unsigned(image=image, reason="nothing offered")

    def test_a_registry_port_is_not_taken_for_a_tag(self):
        assert Unsigned(image="localhost:5000/tool", reason="nothing offered").registry_key == ("localhost:5000", "tool")


class TestAttested:
    def test_a_complete_entry_is_attested(self):
        assert Attested(image="ghcr.io/owner/tool", repository="owner/tool").tier is Tier.ATTESTED

    def test_an_entry_with_no_repository_cannot_be_built(self):
        with pytest.raises(TypeError, match="repository"):
            Attested(image="ghcr.io/owner/tool")  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        "repository",
        [
            pytest.param("tool", id="no-owner"),
            pytest.param("a/b/c", id="too-deep"),
            pytest.param("a b/c", id="space"),
            pytest.param("-a/b", id="leading-dash"),
            pytest.param("", id="empty"),
        ],
    )
    def test_a_repository_that_is_not_owner_slash_name_is_refused(self, repository):
        with pytest.raises(ValueError, match="repository must be owner/name"):
            Attested(image="ghcr.io/owner/tool", repository=repository)


class TestSigned:
    def test_an_identity_written_out_is_a_signed_entry(self):
        entry = Signed(image="owner/tool", identity=IDENTITY, issuer=ISSUER)
        assert (entry.tier, entry.identity, entry.identity_regexp, entry.key) == (Tier.SIGNED, IDENTITY, None, None)

    def test_an_anchored_pattern_is_a_signed_entry(self):
        assert Signed(image="owner/tool", identity_regexp=PATTERN, issuer=ISSUER).identity_regexp == PATTERN

    def test_a_committed_key_is_a_signed_entry_that_names_no_identity(self):
        entry = Signed(image="owner/tool", key=KEY)
        assert (entry.tier, entry.key, entry.identity, entry.issuer) == (Tier.SIGNED, KEY, None, None)

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            pytest.param({}, "name the certificate identity, or the public key", id="no-identity-and-no-key"),
            pytest.param({"issuer": ISSUER}, "name the certificate identity, or the public key", id="issuer-alone"),
            pytest.param({"identity": ""}, "name the certificate identity, or the public key", id="empty-identity"),
            pytest.param({"identity": IDENTITY, "identity_regexp": PATTERN, "issuer": ISSUER}, "not both", id="identity-and-pattern"),
            pytest.param({"identity": IDENTITY}, "issuer must be an https URL", id="identity-without-issuer"),
            pytest.param({"identity": IDENTITY, "issuer": "http://issuer.example"}, "issuer must be an https URL", id="plain-http-issuer"),
            pytest.param({"identity": "https://github.com/o/r/a b", "issuer": ISSUER}, "must not contain whitespace", id="whitespace-in-identity"),
            pytest.param({"identity": IDENTITY, "issuer": ISSUER, "key": KEY}, "alternatives, not both", id="identity-and-key"),
            pytest.param({"issuer": ISSUER, "key": KEY}, "alternatives, not both", id="issuer-and-key"),
        ],
    )
    def test_an_entry_that_would_accept_any_signer_or_two_alternatives_is_refused(self, change, message):
        with pytest.raises(ValueError, match=message):
            Signed(image="owner/tool", **change)

    @pytest.mark.parametrize(
        "pattern",
        [
            pytest.param(r"https://github\.com/owner/tool/.*$", id="not-anchored-at-the-start"),
            pytest.param(r"^https://github\.com/owner/tool/.*", id="not-anchored-at-the-end"),
            pytest.param(r"^https://github\.com/owner/tool\$", id="end-anchor-escaped"),
            pytest.param(r"^https://.*$", id="wildcard-host"),
            pytest.param(r"^.*$", id="matches-everything"),
            pytest.param(r"^http://github\.com/owner/tool$", id="plain-http"),
        ],
    )
    def test_a_pattern_that_could_match_inside_a_longer_identity_is_refused(self, pattern):
        with pytest.raises(ValueError, match="identity_regexp must be anchored"):
            Signed(image="owner/tool", identity_regexp=pattern, issuer=ISSUER)

    def test_a_pattern_that_is_not_a_regular_expression_is_refused(self):
        with pytest.raises(ValueError, match="is not a pattern"):
            Signed(image="owner/tool", identity_regexp="^https://github.com/(owner$", issuer=ISSUER)

    @pytest.mark.parametrize(
        "key",
        [
            pytest.param("keys/tool.pub", id="outside-the-keys-directory"),
            pytest.param(f"{registry.KEYS}/tool.asc", id="not-a-pub-file"),
            pytest.param(f"{registry.KEYS}/sub/tool.pub", id="nested"),
            pytest.param(f"{registry.KEYS}/../tool.pub", id="parent-directory"),
            pytest.param(f"{registry.KEYS}/-tool.pub", id="leading-dash"),
        ],
    )
    def test_a_key_must_be_a_pub_file_directly_under_the_keys_directory(self, key):
        with pytest.raises(ValueError, match=r"key must be a \.pub file directly under"):
            Signed(image="owner/tool", key=key)


class TestUnsigned:
    def test_an_entry_says_why_nothing_can_be_verified(self):
        assert Unsigned(image="owner/tool", reason="the publisher signs nothing").tier is Tier.UNSIGNED

    @pytest.mark.parametrize("reason", [pytest.param("", id="empty"), pytest.param("  ", id="blank")])
    def test_an_entry_with_no_reason_is_refused(self, reason):
        with pytest.raises(ValueError, match="say why"):
            Unsigned(image="owner/tool", reason=reason)


class TestValidate:
    def test_two_entries_for_one_repository_are_refused_whatever_their_tiers(self):
        entries = (Unsigned(image="ghcr.io/owner/tool", reason="r"), Attested(image="ghcr.io/owner/tool", repository="owner/tool"))
        with pytest.raises(ValueError, match=r"ghcr\.io/owner/tool and ghcr\.io/owner/tool name the same image repository"):
            registry.validate(entries)


SMALLSTEP = "https://github.com/smallstep/workflows/.github/workflows/docker-buildx-push.yml@refs/heads/main"


class TestRealRegistry:
    @staticmethod
    def pinned_repositories() -> set[tuple[str, str]]:
        """Every image repository the tree names, with or without a digest."""
        parsed = (remote.parse_image(text) for text in remote.collect(remote.REPO_ROOT).images)
        return {(image.registry, image.repository) for image in parsed}

    def test_each_repository_has_one_entry(self):
        assert len({entry.registry_key for entry in ENTRIES}) == len(ENTRIES)

    def test_every_image_repository_the_tree_pins_has_an_entry(self):
        assert self.pinned_repositories() - {entry.registry_key for entry in ENTRIES} == set()

    def test_no_entry_names_a_repository_the_tree_does_not_pin(self):
        assert {entry.registry_key for entry in ENTRIES} - self.pinned_repositories() == set()

    def test_each_image_has_the_tier_its_publisher_offers(self):
        assert {entry.image: entry.tier for entry in ENTRIES if entry.tier is not Tier.UNSIGNED} == {
            "ghcr.io/lissy93/dashy": Tier.ATTESTED,
            "ghcr.io/wenenhoe/caddy-digitalocean": Tier.ATTESTED,
            "ghcr.io/wenenhoe/molecule-dind": Tier.ATTESTED,
            "ghcr.io/wenenhoe/wastebin": Tier.ATTESTED,
            "openbao/openbao": Tier.SIGNED,
            "smallstep/step-ca": Tier.SIGNED,
            "smallstep/step-cli": Tier.SIGNED,
            "curlimages/curl": Tier.SIGNED,
        }

    def test_the_attested_image_is_attested_for_the_repository_that_builds_it(self):
        dashy = next(entry for entry in ENTRIES if entry.image == "ghcr.io/lissy93/dashy")
        assert isinstance(dashy, Attested)
        assert dashy.repository == "Lissy93/dashy"

    def test_the_signed_images_fix_the_identity_their_publisher_signs_with(self):
        signed = {entry.image: entry for entry in ENTRIES if isinstance(entry, Signed)}
        assert {image: (entry.identity, entry.identity_regexp, entry.issuer, entry.key) for image, entry in signed.items()} == {
            "openbao/openbao": (
                None,
                r"^https://github\.com/openbao/openbao/\.github/workflows/release-images\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$",
                "https://token.actions.githubusercontent.com",
                None,
            ),
            "smallstep/step-ca": (SMALLSTEP, None, "https://token.actions.githubusercontent.com", None),
            "smallstep/step-cli": (SMALLSTEP, None, "https://token.actions.githubusercontent.com", None),
            "curlimages/curl": (None, None, None, f"{registry.KEYS}/curl.pub"),
        }

    def test_the_openbao_pattern_matches_a_version_tag_of_its_release_workflow_and_nothing_else(self):
        pattern = re.compile(next(entry.identity_regexp for entry in ENTRIES if entry.image == "openbao/openbao"))
        workflow = "https://github.com/openbao/openbao/.github/workflows/release-images.yml"
        assert [
            bool(pattern.search(identity))
            for identity in (
                f"{workflow}@refs/tags/v2.7.1",
                f"{workflow}@refs/heads/main",
                f"{workflow}@refs/tags/v2.7.1-evil",
                f"x{workflow}@refs/tags/v2.7.1",
                workflow.replace("release-images", "release") + "@refs/tags/v2.7.1",
            )
        ] == [True, False, False, False, False]

    def test_every_committed_key_is_exactly_one_public_key_and_every_signed_entry_names_one(self, subtests):
        committed = sorted(path.name for path in (remote.REPO_ROOT / registry.KEYS).glob("*"))
        assert committed == sorted(entry.key.rsplit("/", 1)[1] for entry in ENTRIES if isinstance(entry, Signed) and entry.key)
        for name in committed:
            with subtests.test(key=name):
                text = (remote.REPO_ROOT / registry.KEYS / name).read_text()
                assert (text.count("-----BEGIN PUBLIC KEY-----"), text.count("-----END PUBLIC KEY-----")) == (1, 1)

    def test_the_images_the_repository_pins_by_digest_are_attested_for_this_repository(self, subtests):
        pinned = {pin.registry_key for pin in pins.pinned(remote.collect(remote.REPO_ROOT))[0]}
        own = [entry for entry in ENTRIES if entry.image.startswith("ghcr.io/wenenhoe/") and entry.registry_key in pinned]
        assert len(own) == 3
        for entry in own:
            with subtests.test(image=entry.image):
                assert (entry.tier, entry.repository) == (Tier.ATTESTED, "wenenhoe/homelab")
