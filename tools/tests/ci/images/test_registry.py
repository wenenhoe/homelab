"""Tests for ci.images.registry: tag derivation, refs, and the pin check.

Tag sources run against Dockerfile text; the pin check runs against a
scratch tree with one drifting file at a time, so each error is shown to
fire; the last class checks the real repo.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.images import registry as reg


class FinalFromTests(unittest.TestCase):
    SOURCE = staticmethod(reg.final_from("caddy"))

    def test_takes_the_tag_of_the_last_from(self):
        self.assertEqual(self.SOURCE("FROM caddy:2.11.4-builder AS builder\nRUN x\nFROM caddy:2.11.4\nCOPY a b\n"), "2.11.4")

    def test_an_as_alias_and_platform_flag_are_ignored(self):
        self.assertEqual(self.SOURCE("FROM --platform=linux/amd64 caddy:2.11 AS final\n"), "2.11")

    def test_is_case_insensitive_about_the_keywords(self):
        self.assertEqual(self.SOURCE("from caddy:2.1.0 as x\n"), "2.1.0")

    def test_a_different_final_image_is_an_error(self):
        with self.assertRaisesRegex(reg.ImageError, "final FROM is 'alpine'"):
            self.SOURCE("FROM caddy:2.11.4 AS b\nFROM alpine:3.20\n")

    def test_no_from_is_an_error(self):
        with self.assertRaisesRegex(reg.ImageError, "no FROM"):
            self.SOURCE("# nothing\n")

    def test_an_untagged_or_odd_tag_is_an_error(self):
        for line in ("FROM caddy\n", "FROM caddy:latest\n", "FROM caddy:2.11.4-alpine\n"):
            with self.subTest(line=line), self.assertRaisesRegex(reg.ImageError, "must be a version"):
                self.SOURCE(line)

    def test_a_registry_port_is_not_mistaken_for_a_tag(self):
        with self.assertRaisesRegex(reg.ImageError, "must be a version"):
            reg.final_from("registry:5000/caddy")("FROM registry:5000/caddy\n")


class FromImageTests(unittest.TestCase):
    SOURCE = staticmethod(reg.from_image("quxfoo/wastebin"))

    def test_finds_the_one_matching_from_among_others(self):
        self.assertEqual(self.SOURCE("FROM busybox:1.38.0-musl AS d\nFROM quxfoo/wastebin:3.7.2\nCOPY --from=busybox:1.38.0-musl /a /b\n"), "3.7.2")

    def test_zero_or_two_matches_is_an_error(self):
        for text in ("FROM busybox:1.38.0\n", "FROM quxfoo/wastebin:1.0.0\nFROM quxfoo/wastebin:2.0.0\n"):
            with self.subTest(text=text), self.assertRaisesRegex(reg.ImageError, "exactly one"):
                self.SOURCE(text)


class ArgVersionTests(unittest.TestCase):
    SOURCE = staticmethod(reg.arg_version("CODERABBIT_VERSION"))

    def test_reads_the_one_arg(self):
        self.assertEqual(self.SOURCE("FROM ubuntu:26.04\nARG CODERABBIT_VERSION=0.8.0\nARG CODERABBIT_SHA256=abc\n"), "0.8.0")

    def test_zero_two_or_malformed_is_an_error(self):
        for text in (
            "FROM x\n",
            "ARG CODERABBIT_VERSION=1.0.0\nARG CODERABBIT_VERSION=1.0.1\n",
            "ARG CODERABBIT_VERSION=1.0\n",
            "ARG CODERABBIT_VERSION=latest\n",
        ):
            with self.subTest(text=text), self.assertRaises(reg.ImageError):
                self.SOURCE(text)

    def test_the_sha_arg_is_not_the_version(self):
        with self.assertRaisesRegex(reg.ImageError, "exactly one"):
            self.SOURCE("ARG CODERABBIT_SHA256=abc\n")


class ScratchTree(unittest.TestCase):
    """A repo with one image of each shape, all in agreement."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.write("docker/caddy/Dockerfile", "FROM caddy:2.11.4-builder AS builder\nFROM caddy:2.11.4\n")
        self.write("docker/caddy/compose.yaml", "services:\n  caddy:\n    image: ghcr.io/wenenhoe/caddy-digitalocean:2.11.4\n")
        self.write("docker/wastebin/Dockerfile", "FROM busybox:1.38.0 AS d\nFROM quxfoo/wastebin:3.7.2\n")
        self.write("docker/wastebin/compose.yaml.j2", "services:\n  w:\n    image: ghcr.io/wenenhoe/wastebin:3.7.2\n")
        self.write("docker/molecule-dind/Dockerfile", "FROM geerlingguy/x:latest\n")
        self.write("tools/coderabbit-review/Dockerfile", "ARG CODERABBIT_VERSION=0.8.0\n")
        self.write("ansible/roles/r/molecule/default/molecule.yml", "platforms:\n  - name: x\n    image: ghcr.io/wenenhoe/molecule-dind:latest\n")

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


class RefsTests(ScratchTree):
    def test_version_tag_first_then_extras(self):
        self.assertEqual(
            reg.refs(self.root, reg.IMAGES["coderabbit-review"]), ["ghcr.io/wenenhoe/coderabbit-review:0.8.0", "ghcr.io/wenenhoe/coderabbit-review:latest"]
        )

    def test_the_image_name_is_not_the_directory_name(self):
        self.assertEqual(reg.refs(self.root, reg.IMAGES["caddy"]), ["ghcr.io/wenenhoe/caddy-digitalocean:2.11.4"])

    def test_a_constant_tag_is_not_repeated_as_an_extra(self):
        image = reg.Image("x", "x", "docker/molecule-dind", reg.constant("latest"), extra_tags=("latest",))
        self.assertEqual(reg.refs(self.root, image), ["ghcr.io/wenenhoe/x:latest"])

    def test_error_names_the_image_and_file(self):
        self.write("docker/wastebin/Dockerfile", "FROM busybox:1.38.0\n")
        with self.assertRaisesRegex(reg.ImageError, r"wastebin: docker/wastebin/Dockerfile: expected exactly one FROM quxfoo/wastebin"):
            reg.resolve_version(self.root, reg.IMAGES["wastebin"])

    def test_missing_dockerfile_is_an_error(self):
        (self.root / "docker/wastebin/Dockerfile").unlink()
        with self.assertRaisesRegex(reg.ImageError, "can't read"):
            reg.resolve_version(self.root, reg.IMAGES["wastebin"])

    def test_lookup_of_an_unknown_image_lists_the_known_ones(self):
        with self.assertRaisesRegex(reg.ImageError, "known: caddy"):
            reg.lookup("nope")


class CheckPinsTests(ScratchTree):
    def test_agreeing_tree_has_no_errors(self):
        self.assertEqual(reg.check_pins(self.root), [])

    def test_compose_pin_behind_the_dockerfile_is_an_error(self):
        self.write("docker/caddy/Dockerfile", "FROM caddy:2.12.0-builder AS builder\nFROM caddy:2.12.0\n")
        (error,) = reg.check_pins(self.root)
        self.assertIn("docker/caddy/compose.yaml: pins ghcr.io/wenenhoe/caddy-digitalocean:2.11.4, but the Dockerfile publishes 2.12.0", error)

    def test_templated_compose_files_are_checked_too(self):
        self.write("docker/wastebin/compose.yaml.j2", "    image: ghcr.io/wenenhoe/wastebin:3.7.1\n")
        (error,) = reg.check_pins(self.root)
        self.assertIn("compose.yaml.j2", error)

    def test_a_compose_pin_with_no_tag_is_an_error(self):
        self.write("docker/wastebin/compose.yaml.j2", "    image: ghcr.io/wenenhoe/wastebin\n")
        (error,) = reg.check_pins(self.root)
        self.assertIn("(no tag)", error)

    def test_a_quoted_image_is_still_read(self):
        self.write("docker/wastebin/compose.yaml.j2", "    image: 'ghcr.io/wenenhoe/wastebin:1.0.0'\n")
        self.assertEqual(len(reg.check_pins(self.root)), 1)

    def test_a_commented_out_pin_is_ignored(self):
        self.write("docker/wastebin/compose.yaml.j2", "    # image: ghcr.io/wenenhoe/wastebin:0.0.1\n    image: ghcr.io/wenenhoe/wastebin:3.7.2\n")
        self.assertEqual(reg.check_pins(self.root), [])

    def test_third_party_images_are_not_this_checks_business(self):
        self.write("docker/caddy/compose.yaml", "    image: redis:7\n    image: ghcr.io/other/thing:1\n")
        self.assertEqual(reg.check_pins(self.root), [])

    def test_a_self_built_image_with_no_entry_is_an_error(self):
        self.write("docker/wastebin/compose.yaml.j2", "    image: ghcr.io/wenenhoe/mystery:1.0.0\n")
        (error,) = reg.check_pins(self.root)
        self.assertIn("pins ghcr.io/wenenhoe/mystery, which no image entry publishes", error)

    def test_a_dockerfile_with_no_entry_is_an_error(self):
        self.write("docker/newapp/Dockerfile", "FROM alpine:3.20\n")
        (error,) = reg.check_pins(self.root)
        self.assertIn("docker/newapp/Dockerfile has no entry", error)

    def test_an_entry_with_no_dockerfile_is_an_error(self):
        (self.root / "docker/molecule-dind/Dockerfile").unlink()
        (error,) = reg.check_pins(self.root)
        self.assertIn("molecule-dind: docker/molecule-dind/Dockerfile doesn't exist", error)

    def test_an_unresolvable_dockerfile_is_reported_not_raised(self):
        self.write("tools/coderabbit-review/Dockerfile", "ARG CODERABBIT_VERSION=latest\n")
        (error,) = reg.check_pins(self.root)
        self.assertIn("coderabbit-review", error)

    def test_molecule_scenario_on_an_unpublished_tag_is_an_error(self):
        self.write("ansible/roles/r/molecule/default/molecule.yml", "    image: ghcr.io/wenenhoe/molecule-dind:v2\n")
        (error,) = reg.check_pins(self.root)
        self.assertIn("molecule.yml: uses ghcr.io/wenenhoe/molecule-dind:v2", error)

    def test_molecule_scenario_on_an_unknown_image_is_an_error(self):
        self.write("ansible/roles/r/molecule/default/molecule.yml", "    image: ghcr.io/wenenhoe/other:latest\n")
        (error,) = reg.check_pins(self.root)
        self.assertIn("which no image entry publishes", error)

    def test_every_disagreement_is_reported_not_just_the_first(self):
        self.write("docker/wastebin/compose.yaml.j2", "    image: ghcr.io/wenenhoe/wastebin:1.0.0\n")
        self.write("docker/caddy/compose.yaml", "    image: ghcr.io/wenenhoe/caddy-digitalocean:1.0.0\n")
        self.assertEqual(len(reg.check_pins(self.root)), 2)


class CliTests(ScratchTree):
    def main(self, *argv: str) -> tuple[int, str]:
        out = self.root / "out.txt"
        with patch.object(reg, "REPO_ROOT", self.root), patch.dict(os.environ, {"GITHUB_OUTPUT": str(out)}):
            code = reg.main(list(argv))
        return code, out.read_text() if out.exists() else ""

    def test_tags_writes_version_and_comma_separated_tags(self):
        code, out = self.main("tags", "coderabbit-review")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["version=0.8.0", "tags=ghcr.io/wenenhoe/coderabbit-review:0.8.0,ghcr.io/wenenhoe/coderabbit-review:latest"])

    def test_tags_for_an_unresolvable_image_fails_the_job(self):
        self.write("docker/wastebin/Dockerfile", "FROM busybox:1\n")
        self.assertEqual(self.main("tags", "wastebin")[0], 1)

    def test_tags_for_an_unknown_image_fails_the_job(self):
        self.assertEqual(self.main("tags", "nope")[0], 1)

    def test_check_pins_exit_codes(self):
        self.assertEqual(self.main("check-pins")[0], 0)
        self.write("docker/caddy/compose.yaml", "    image: ghcr.io/wenenhoe/caddy-digitalocean:0.0.1\n")
        self.assertEqual(self.main("check-pins")[0], 1)


class RealTreeTests(unittest.TestCase):
    def test_every_pin_in_the_repo_matches_what_is_published(self):
        self.assertEqual(reg.check_pins(reg.REPO_ROOT), [])

    def test_every_entry_resolves(self):
        for key, image in reg.IMAGES.items():
            with self.subTest(image=key):
                self.assertTrue(reg.refs(reg.REPO_ROOT, image))

    def test_the_resolver_agrees_with_the_grep_the_workflows_used(self):
        # build-caddy-image.yml: the last `FROM caddy:<no dash>` line;
        # build-wastebin-image.yml: the `FROM quxfoo/wastebin:` line.
        import re

        for key, pattern in (("caddy", r"^FROM caddy:([^-\s]+)$"), ("wastebin", r"^FROM quxfoo/wastebin:(\S+)$")):
            with self.subTest(image=key):
                lines = [m.group(1) for line in reg.IMAGES[key].dockerfile(reg.REPO_ROOT).read_text().splitlines() if (m := re.match(pattern, line))]
                self.assertEqual(reg.resolve_version(reg.REPO_ROOT, reg.IMAGES[key]), lines[-1])

    def test_the_coderabbit_arg_is_read_from_the_dockerfile(self):
        text = reg.IMAGES["coderabbit-review"].dockerfile(reg.REPO_ROOT).read_text()
        self.assertIn(f"ARG CODERABBIT_VERSION={reg.resolve_version(reg.REPO_ROOT, reg.IMAGES['coderabbit-review'])}\n", text)


if __name__ == "__main__":
    unittest.main()
