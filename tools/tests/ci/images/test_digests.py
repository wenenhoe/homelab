"""Tests for ci.images.digests: every image reference carries a digest or is listed as floating.

The check runs against a scratch tree with one drift at a time, so each error
is shown to fire; the last class checks the real repo.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ci.images import digests as dg
from ci.images import remote

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def tree(root):
    """A tree whose only image is pinned, with an empty Renovate config."""
    write(root, remote.RENOVATE_CONFIG, "{ customManagers: [] }")
    write(root, "docker/app/compose.yaml", f"    image: redis:7@{A}\n")
    return root


class TestPinned:
    def test_a_pinned_tree_has_no_errors(self, tree):
        assert dg.check(tree, floating={}) == []

    @pytest.mark.parametrize(
        ("line", "image"),
        [
            pytest.param("    image: redis:7\n", "redis:7", id="tag-only"),
            pytest.param("    image: redis\n", "redis", id="no-tag"),
            pytest.param("    image: ghcr.io/x/y:1.2\n", "ghcr.io/x/y:1.2", id="other-registry"),
        ],
    )
    def test_an_unpinned_reference_is_an_error_naming_the_file(self, tree, line, image):
        write(tree, "docker/other/compose.yaml", line)
        (error,) = dg.check(tree, floating={})
        assert error.startswith(f"{image} (docker/other/compose.yaml): has no @sha256 digest")

    def test_a_dockerfile_from_is_judged_too(self, tree):
        write(tree, "docker/app/Dockerfile", "FROM caddy:2.11\n")
        (error,) = dg.check(tree, floating={})
        assert "caddy:2.11 (docker/app/Dockerfile)" in error

    def test_a_reference_in_a_renovate_tracked_pin_is_judged_too(self, tree):
        write(
            tree,
            remote.RENOVATE_CONFIG,
            """{ customManagers: [{
              customType: "regex", managerFilePatterns: ["/^unit\\\\.service$/"], datasourceTemplate: "docker",
              matchStrings: ["rclone/rclone:(?<currentValue>[0-9.]+)"], depNameTemplate: "rclone/rclone",
            }] }""",
        )
        write(tree, "unit.service", "ExecStart=docker run rclone/rclone:1.75\n")
        (error,) = dg.check(tree, floating={})
        assert error.startswith("rclone/rclone:1.75 (unit.service)")

    def test_references_that_cannot_be_pinned_are_not_judged(self, tree):
        write(tree, "docker/other/compose.yaml", "    image: buildapp:local\n    image: {{ app_image }}\n")
        write(tree, "docker/other/Dockerfile", "FROM scratch\n")
        assert dg.check(tree, floating={}) == []

    @pytest.mark.parametrize("digest", ["sha256:abc", "sha256:" + "A" * 64, "md5:" + "a" * 32])
    def test_a_malformed_digest_is_an_error(self, tree, digest):
        write(tree, "docker/other/compose.yaml", f"    image: redis:7@{digest}\n")
        assert any("is not a sha256 digest" in e for e in dg.check(tree, floating={}))


class TestConsistency:
    def test_one_tag_pinned_to_two_digests_is_an_error(self, tree):
        write(tree, "docker/other/compose.yaml", f"    image: redis:7@{B}\n")
        (error,) = dg.check(tree, floating={})
        assert error.startswith("redis:7 is pinned to 2 different digests")
        assert A in error and B in error

    def test_the_same_digest_in_two_files_is_fine(self, tree):
        write(tree, "docker/other/compose.yaml", f"    image: redis:7@{A}\n")
        assert dg.check(tree, floating={}) == []

    def test_two_tags_of_one_image_may_have_different_digests(self, tree):
        write(tree, "docker/other/compose.yaml", f"    image: redis:8@{B}\n")
        assert dg.check(tree, floating={}) == []


class TestFloating:
    def test_a_listed_reference_may_stay_unpinned(self, tree):
        write(tree, "docker/other/compose.yaml", "    image: hello-world\n")
        assert dg.check(tree, floating={"hello-world": "why"}) == []

    def test_an_entry_nothing_names_any_more_is_an_error(self, tree):
        (error,) = dg.check(tree, floating={"hello-world": "why"})
        assert error == "hello-world is listed in ci.images.digests.FLOATING but is not named anywhere; remove the entry"

    def test_an_entry_that_is_pinned_after_all_is_an_error(self, tree):
        (error,) = dg.check(tree, floating={"redis:7": "why"})
        assert "but is pinned; remove the entry" in error

    def test_an_entry_covers_the_reference_exactly_not_its_other_tags(self, tree):
        write(tree, "docker/other/compose.yaml", "    image: hello-world:2\n")
        errors = dg.check(tree, floating={"hello-world": "why"})
        assert any(e.startswith("hello-world:2 ") for e in errors)


class TestMain:
    def test_a_broken_renovate_config_is_an_error_exit(self, tree, monkeypatch, capsys):
        (tree / remote.RENOVATE_CONFIG).unlink()
        monkeypatch.setattr(dg, "REPO_ROOT", tree)
        assert dg.main(["check"]) == 1
        assert "can't read" in capsys.readouterr().err

    def test_errors_print_as_annotations_and_fail(self, tree, monkeypatch, capsys):
        write(tree, "docker/other/compose.yaml", "    image: redis:7\n")
        monkeypatch.setattr(dg, "REPO_ROOT", tree)
        monkeypatch.setattr(dg, "FLOATING", {})
        assert dg.main(["check"]) == 1
        assert capsys.readouterr().out.startswith("::error::redis:7 (docker/other/compose.yaml)")


class TestRealRepo:
    def test_the_repo_is_pinned_apart_from_its_listed_exceptions(self):
        assert dg.check(dg.REPO_ROOT) == []

    def test_every_exception_has_a_reason(self, subtests):
        for name, reason in dg.FLOATING.items():
            with subtests.test(name=name):
                assert len(reason) > 20
