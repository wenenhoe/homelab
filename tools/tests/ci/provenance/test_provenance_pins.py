"""Tests for ci.provenance.pins.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
from ci.images import remote
from ci.provenance import pins
from ci.provenance.pins import Pin

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
D3 = "sha256:" + "3" * 64


def collected(**images: list[str]) -> remote.Collected:
    """A collection whose keys are references: `collected(**{"ghcr.io/o/t:1@sha256:...": ["docker/a/compose.yaml"]})`."""
    return remote.Collected(images=images)


class TestPinned:
    def test_a_digest_is_read_with_the_repository_and_the_files_that_pin_it(self):
        found, problems = pins.pinned(collected(**{f"ghcr.io/owner/tool:1.0@{D1}": ["docker/tool/compose.yaml", "ansible/defaults.yaml"]}))
        assert (found, problems) == ([Pin("ghcr.io", "owner/tool", D1, ("docker/tool/compose.yaml", "ansible/defaults.yaml"))], [])

    def test_a_reference_with_no_digest_has_nothing_to_verify_and_is_left_out(self):
        assert pins.pinned(collected(**{"ghcr.io/owner/tool:1.0": ["docker/tool/compose.yaml"]})) == ([], [])

    def test_one_digest_named_by_two_tags_is_one_pin_with_both_sources(self):
        found, _ = pins.pinned(
            collected(
                **{f"ghcr.io/owner/tool:1.0@{D1}": ["docker/a/compose.yaml"], f"ghcr.io/owner/tool:stable@{D1}": ["ansible/b.yaml", "docker/a/compose.yaml"]}
            )
        )
        assert found == [Pin("ghcr.io", "owner/tool", D1, ("docker/a/compose.yaml", "ansible/b.yaml"))]

    def test_every_digest_pinned_for_a_repository_is_a_pin_of_its_own(self):
        found, _ = pins.pinned(collected(**{f"ghcr.io/owner/tool:1.0@{D2}": ["a"], f"ghcr.io/owner/tool:1.0-builder@{D1}": ["b"]}))
        assert [(pin.repository, pin.digest) for pin in found] == [("owner/tool", D1), ("owner/tool", D2)]

    def test_pins_of_different_repositories_stay_apart(self):
        found, _ = pins.pinned(collected(**{f"ghcr.io/owner/tool:1@{D1}": ["a"], f"ghcr.io/owner/other:1@{D1}": ["b"]}))
        assert [pin.registry_key for pin in found] == [("ghcr.io", "owner/other"), ("ghcr.io", "owner/tool")]


class TestReference:
    @pytest.mark.parametrize(
        ("text", "reference"),
        [
            pytest.param(f"ghcr.io/owner/tool:1@{D1}", f"ghcr.io/owner/tool@{D1}", id="ghcr"),
            pytest.param(f"openbao/openbao:2.7.1@{D1}", f"docker.io/openbao/openbao@{D1}", id="docker-hub-namespace"),
            pytest.param(f"ubuntu:26.04@{D1}", f"docker.io/library/ubuntu@{D1}", id="docker-hub-official-image"),
            pytest.param(f"ghcr.io/owner/group/tool@{D1}", f"ghcr.io/owner/group/tool@{D1}", id="no-tag-and-a-nested-repository"),
        ],
    )
    def test_the_name_given_to_the_tools_is_the_repository_at_its_digest_and_never_the_tag(self, text, reference):
        found, _ = pins.pinned(collected(**{text: ["a"]}))
        assert [pin.reference for pin in found] == [reference]


class TestRefusedReferences:
    @pytest.mark.parametrize(
        ("text", "reason"),
        [
            pytest.param("ghcr.io/Owner/tool:1@sha256:" + "1" * 64, "not a sha256 digest reference a registry accepts", id="upper-case-repository"),
            pytest.param("ghcr.io/owner/tool:1@sha512:" + "1" * 64, "not a sha256 digest reference a registry accepts", id="other-algorithm"),
            pytest.param("ghcr.io/owner/tool:1@sha256:" + "1" * 63, "not a sha256 digest reference a registry accepts", id="short-digest"),
            pytest.param("ghcr.io/owner/tool:1@sha256:" + "G" * 64, "not a sha256 digest reference a registry accepts", id="digest-not-hex"),
            pytest.param("ghcr.io/owner/tool:1@", "not a sha256 digest reference a registry accepts", id="empty-digest"),
            pytest.param("ghcr.io/owner/--flag:1@sha256:" + "1" * 64, "not a sha256 digest reference a registry accepts", id="repository-that-opens-on-dashes"),
            pytest.param("ghcr.io/owner/tool/:1@sha256:" + "1" * 64, "not an image reference", id="trailing-slash"),
            pytest.param("ghcr.io/owner/to ol:1@sha256:" + "1" * 64, "not an image reference", id="space"),
        ],
    )
    def test_a_reference_that_cannot_be_handed_to_a_tool_is_a_problem_and_not_a_pin(self, text, reason):
        found, problems = pins.pinned(collected(**{text: ["docker/a/compose.yaml"]}))
        assert found == []
        assert len(problems) == 1
        assert problems[0].startswith(f"{text} (docker/a/compose.yaml): ")
        assert reason in problems[0]

    def test_a_refused_reference_does_not_hide_the_valid_pins_beside_it(self):
        found, problems = pins.pinned(collected(**{f"ghcr.io/owner/tool:1@{D1}": ["a"], "ghcr.io/Owner/bad:1@sha256:" + "1" * 64: ["b"]}))
        assert ([pin.repository for pin in found], len(problems)) == (["owner/tool"], 1)


class TestRealTree:
    def test_every_digest_the_tree_pins_is_taken_and_none_is_refused(self):
        real = remote.collect(remote.REPO_ROOT)
        found, problems = pins.pinned(real)
        assert problems == []
        pinned_refs = {text for text in real.images if "@" in text}
        assert {(pin.registry, pin.repository, pin.digest) for pin in found} == {
            (i.registry, i.repository, i.reference) for i in map(remote.parse_image, pinned_refs)
        }
        assert found
