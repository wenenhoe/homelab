"""Tests for ci.images.registry: tag derivation, refs, and the pin check.

Tag sources run against Dockerfile text; the pin check runs against a
scratch tree with one drifting file at a time, so each error is shown to
fire; the last class checks the real repo.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from ci.images import registry as reg


class TestFinalFrom:
    SOURCE = staticmethod(reg.final_from("caddy"))

    @pytest.mark.parametrize(
        ("text", "tag"),
        [
            pytest.param("FROM caddy:2.11.4-builder AS builder\nRUN x\nFROM caddy:2.11.4\nCOPY a b\n", "2.11.4", id="last-from"),
            pytest.param("FROM --platform=linux/amd64 caddy:2.11 AS final\n", "2.11", id="as-alias-and-platform-flag"),
            pytest.param("from caddy:2.1.0 as x\n", "2.1.0", id="lowercase-keywords"),
        ],
    )
    def test_takes_the_tag_of_the_final_from(self, text, tag):
        assert self.SOURCE(text) == tag

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            pytest.param("FROM caddy:2.11.4 AS b\nFROM alpine:3.20\n", "final FROM is 'alpine'", id="a-different-final-image"),
            pytest.param("# nothing\n", "no FROM", id="no-from"),
        ],
    )
    def test_a_final_from_that_is_not_the_image_is_an_error(self, text, message):
        with pytest.raises(reg.ImageError, match=message):
            self.SOURCE(text)

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param("FROM caddy\n", id="untagged"),
            pytest.param("FROM caddy:latest\n", id="latest"),
            pytest.param("FROM caddy:2.11.4-alpine\n", id="variant-suffix"),
        ],
    )
    def test_an_untagged_or_odd_tag_is_an_error(self, line):
        with pytest.raises(reg.ImageError, match="must be a version"):
            self.SOURCE(line)

    def test_a_registry_port_is_not_mistaken_for_a_tag(self):
        with pytest.raises(reg.ImageError, match="must be a version"):
            reg.final_from("registry:5000/caddy")("FROM registry:5000/caddy\n")


class TestFromImage:
    SOURCE = staticmethod(reg.from_image("quxfoo/wastebin"))

    def test_finds_the_one_matching_from_among_others(self):
        assert self.SOURCE("FROM busybox:1.38.0-musl AS d\nFROM quxfoo/wastebin:3.7.2\nCOPY --from=busybox:1.38.0-musl /a /b\n") == "3.7.2"

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("FROM busybox:1.38.0\n", id="no-match"),
            pytest.param("FROM quxfoo/wastebin:1.0.0\nFROM quxfoo/wastebin:2.0.0\n", id="two-matches"),
        ],
    )
    def test_zero_or_two_matches_is_an_error(self, text):
        with pytest.raises(reg.ImageError, match="exactly one"):
            self.SOURCE(text)


class TestArgVersion:
    SOURCE = staticmethod(reg.arg_version("CODERABBIT_VERSION"))

    def test_reads_the_one_arg(self):
        assert self.SOURCE("FROM ubuntu:26.04\nARG CODERABBIT_VERSION=0.8.0\nARG CODERABBIT_SHA256=abc\n") == "0.8.0"

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("FROM x\n", id="no-arg"),
            pytest.param("ARG CODERABBIT_VERSION=1.0.0\nARG CODERABBIT_VERSION=1.0.1\n", id="two-args"),
            pytest.param("ARG CODERABBIT_VERSION=1.0\n", id="two-part-version"),
            pytest.param("ARG CODERABBIT_VERSION=latest\n", id="latest"),
        ],
    )
    def test_zero_two_or_malformed_is_an_error(self, text):
        with pytest.raises(reg.ImageError):
            self.SOURCE(text)

    def test_the_sha_arg_is_not_the_version(self):
        with pytest.raises(reg.ImageError, match="exactly one"):
            self.SOURCE("ARG CODERABBIT_SHA256=abc\n")


class Tree:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@pytest.fixture
def tree(root):
    """A repo with one image of each shape, all in agreement."""
    tree = Tree(root)
    tree.write("docker/caddy/Dockerfile", "FROM caddy:2.11.4-builder AS builder\nFROM caddy:2.11.4\n")
    tree.write("docker/caddy/compose.yaml", "services:\n  caddy:\n    image: ghcr.io/wenenhoe/caddy-digitalocean:2.11.4\n")
    tree.write("docker/wastebin/Dockerfile", "FROM busybox:1.38.0 AS d\nFROM quxfoo/wastebin:3.7.2\n")
    tree.write("docker/wastebin/compose.yaml.j2", "services:\n  w:\n    image: ghcr.io/wenenhoe/wastebin:3.7.2\n")
    tree.write("docker/molecule-dind/Dockerfile", "FROM geerlingguy/x:latest\n")
    tree.write("tools/coderabbit-review/Dockerfile", "ARG CODERABBIT_VERSION=0.8.0\n")
    tree.write("ansible/roles/r/molecule/default/molecule.yml", "platforms:\n  - name: x\n    image: ghcr.io/wenenhoe/molecule-dind:latest\n")
    return tree


class TestRefs:
    def test_version_tag_first_then_extras(self, tree):
        assert reg.refs(tree.root, reg.IMAGES["coderabbit-review"]) == ["ghcr.io/wenenhoe/coderabbit-review:0.8.0", "ghcr.io/wenenhoe/coderabbit-review:latest"]

    def test_the_image_name_is_not_the_directory_name(self, tree):
        assert reg.refs(tree.root, reg.IMAGES["caddy"]) == ["ghcr.io/wenenhoe/caddy-digitalocean:2.11.4"]

    def test_a_constant_tag_is_not_repeated_as_an_extra(self, tree):
        image = reg.Image("x", "x", "docker/molecule-dind", reg.constant("latest"), extra_tags=("latest",))
        assert reg.refs(tree.root, image) == ["ghcr.io/wenenhoe/x:latest"]

    def test_error_names_the_image_and_file(self, tree):
        tree.write("docker/wastebin/Dockerfile", "FROM busybox:1.38.0\n")
        with pytest.raises(reg.ImageError, match=r"wastebin: docker/wastebin/Dockerfile: expected exactly one FROM quxfoo/wastebin"):
            reg.resolve_version(tree.root, reg.IMAGES["wastebin"])

    def test_missing_dockerfile_is_an_error(self, tree):
        (tree.root / "docker/wastebin/Dockerfile").unlink()
        with pytest.raises(reg.ImageError, match="can't read"):
            reg.resolve_version(tree.root, reg.IMAGES["wastebin"])

    def test_lookup_of_an_unknown_image_lists_the_known_ones(self):
        with pytest.raises(reg.ImageError, match="known: caddy"):
            reg.lookup("nope")


class TestCheckPins:
    def test_agreeing_tree_has_no_errors(self, tree):
        assert reg.check_pins(tree.root) == []

    @pytest.mark.parametrize(
        ("path", "content", "fragment"),
        [
            pytest.param(
                "docker/caddy/compose.yaml",
                "    image: ghcr.io/wenenhoe/caddy-digitalocean:2.12.0\n",
                "docker/caddy/compose.yaml: pins ghcr.io/wenenhoe/caddy-digitalocean:2.12.0, but the Dockerfile publishes 2.11.4",
                id="compose-pin-ahead-of-the-dockerfile",
            ),
            pytest.param("docker/wastebin/compose.yaml.j2", "    image: ghcr.io/wenenhoe/wastebin:3.8.0\n", "compose.yaml.j2", id="templated-compose-file"),
            pytest.param("docker/wastebin/compose.yaml.j2", "    image: ghcr.io/wenenhoe/wastebin\n", "(no tag)", id="compose-pin-with-no-tag"),
            pytest.param(
                "docker/wastebin/compose.yaml.j2", "    image: ghcr.io/wenenhoe/wastebin:latest\n", "wastebin:latest", id="compose-pin-on-a-non-version-tag"
            ),
            pytest.param(
                "docker/wastebin/compose.yaml.j2",
                "    image: ghcr.io/wenenhoe/mystery:1.0.0\n",
                "pins ghcr.io/wenenhoe/mystery, which no image entry publishes",
                id="self-built-image-with-no-entry",
            ),
            pytest.param("docker/newapp/Dockerfile", "FROM alpine:3.20\n", "docker/newapp/Dockerfile has no entry", id="dockerfile-with-no-entry"),
            pytest.param("tools/coderabbit-review/Dockerfile", "ARG CODERABBIT_VERSION=latest\n", "coderabbit-review", id="unresolvable-dockerfile"),
            pytest.param(
                "ansible/roles/r/molecule/default/molecule.yml",
                "    image: ghcr.io/wenenhoe/molecule-dind:v2\n",
                "molecule.yml: uses ghcr.io/wenenhoe/molecule-dind:v2",
                id="molecule-scenario-on-an-unpublished-tag",
            ),
            pytest.param(
                "ansible/roles/r/molecule/default/molecule.yml",
                "    image: ghcr.io/wenenhoe/other:latest\n",
                "which no image entry publishes",
                id="molecule-scenario-on-an-unknown-image",
            ),
        ],
    )
    def test_one_drifting_file_is_one_error_naming_the_cause(self, tree, path, content, fragment):
        tree.write(path, content)
        (error,) = reg.check_pins(tree.root)
        assert fragment in error

    def test_a_compose_pin_may_lag_the_dockerfile_until_its_tag_is_published(self, tree):
        tree.write("docker/caddy/Dockerfile", "FROM caddy:2.12.0-builder AS builder\nFROM caddy:2.12.0\n")
        assert reg.check_pins(tree.root) == []

    @pytest.mark.parametrize(
        ("pin", "dockerfile", "ahead"),
        [
            pytest.param("2.9.0", "2.10.0", False, id="minor-compared-as-a-number-not-text"),
            pytest.param("2.10.0", "2.9.0", True, id="two-digit-minor-is-ahead-of-a-one-digit-one"),
            pytest.param("2.11.3", "2.11.4", False, id="patch-behind"),
            pytest.param("2.11.5", "2.11.4", True, id="patch-ahead"),
            pytest.param("2.11", "2.11.1", False, id="two-part-pin-behind-a-three-part-version"),
            pytest.param("2.11.1", "2.11", True, id="three-part-pin-ahead-of-a-two-part-version"),
        ],
    )
    def test_versions_are_compared_by_their_numbers(self, tree, pin, dockerfile, ahead):
        tree.write("docker/wastebin/Dockerfile", f"FROM busybox:1.38.0 AS d\nFROM quxfoo/wastebin:{dockerfile}\n")
        tree.write("docker/wastebin/compose.yaml.j2", f"    image: ghcr.io/wenenhoe/wastebin:{pin}\n")
        assert bool(reg.check_pins(tree.root)) is ahead

    def test_a_quoted_image_is_still_read(self, tree):
        tree.write("docker/wastebin/compose.yaml.j2", "    image: 'ghcr.io/wenenhoe/wastebin:9.0.0'\n")
        assert len(reg.check_pins(tree.root)) == 1

    def test_a_commented_out_pin_is_ignored(self, tree):
        tree.write("docker/wastebin/compose.yaml.j2", "    # image: ghcr.io/wenenhoe/wastebin:0.0.1\n    image: ghcr.io/wenenhoe/wastebin:3.7.2\n")
        assert reg.check_pins(tree.root) == []

    def test_third_party_images_are_not_this_checks_business(self, tree):
        tree.write("docker/caddy/compose.yaml", "    image: redis:7\n    image: ghcr.io/other/thing:1\n")
        assert reg.check_pins(tree.root) == []

    def test_an_entry_with_no_dockerfile_is_an_error(self, tree):
        (tree.root / "docker/molecule-dind/Dockerfile").unlink()
        (error,) = reg.check_pins(tree.root)
        assert "molecule-dind: docker/molecule-dind/Dockerfile doesn't exist" in error

    def test_every_disagreement_is_reported_not_just_the_first(self, tree):
        tree.write("docker/wastebin/compose.yaml.j2", "    image: ghcr.io/wenenhoe/wastebin:9.0.0\n")
        tree.write("docker/caddy/compose.yaml", "    image: ghcr.io/wenenhoe/caddy-digitalocean:9.0.0\n")
        assert len(reg.check_pins(tree.root)) == 2


@pytest.fixture
def run_main(tree, monkeypatch):
    def run(*argv: str) -> tuple[int, str]:
        out = tree.root / "out.txt"
        monkeypatch.setattr(reg, "REPO_ROOT", tree.root)
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        code = reg.main(list(argv))
        return code, out.read_text() if out.exists() else ""

    return run


class TestCli:
    def test_tags_writes_version_and_comma_separated_tags(self, run_main):
        code, out = run_main("tags", "coderabbit-review")
        assert code == 0
        assert out.splitlines() == ["version=0.8.0", "tags=ghcr.io/wenenhoe/coderabbit-review:0.8.0,ghcr.io/wenenhoe/coderabbit-review:latest"]

    def test_tags_for_an_unresolvable_image_fails_the_job(self, tree, run_main):
        tree.write("docker/wastebin/Dockerfile", "FROM busybox:1\n")
        assert run_main("tags", "wastebin")[0] == 1

    def test_tags_for_an_unknown_image_fails_the_job(self, run_main):
        assert run_main("tags", "nope")[0] == 1

    def test_check_pins_exit_codes(self, tree, run_main):
        assert run_main("check-pins")[0] == 0
        tree.write("docker/caddy/compose.yaml", "    image: ghcr.io/wenenhoe/caddy-digitalocean:9.9.9\n")
        assert run_main("check-pins")[0] == 1


class TestRealTree:
    def test_every_pin_in_the_repo_matches_what_is_published(self):
        assert reg.check_pins(reg.REPO_ROOT) == []

    def test_every_entry_resolves(self, subtests):
        for key, image in reg.IMAGES.items():
            with subtests.test(image=key):
                assert reg.refs(reg.REPO_ROOT, image)

    @pytest.mark.parametrize(
        ("key", "pattern"),
        [
            pytest.param("caddy", r"^FROM caddy:([^-\s]+)$", id="caddy"),
            pytest.param("wastebin", r"^FROM quxfoo/wastebin:(\S+)$", id="wastebin"),
        ],
    )
    def test_the_resolver_agrees_with_the_grep_the_workflows_used(self, key, pattern):
        # build-caddy-image.yml: the last `FROM caddy:<no dash>` line;
        # build-wastebin-image.yml: the `FROM quxfoo/wastebin:` line.
        lines = [m.group(1) for line in reg.IMAGES[key].dockerfile(reg.REPO_ROOT).read_text().splitlines() if (m := re.match(pattern, line))]
        assert reg.resolve_version(reg.REPO_ROOT, reg.IMAGES[key]) == lines[-1]

    def test_the_coderabbit_arg_is_read_from_the_dockerfile(self):
        text = reg.IMAGES["coderabbit-review"].dockerfile(reg.REPO_ROOT).read_text()
        assert f"ARG CODERABBIT_VERSION={reg.resolve_version(reg.REPO_ROOT, reg.IMAGES['coderabbit-review'])}\n" in text
