"""Tests for ci.checksums.pins, on scratch trees and on the real one.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from ci.checksums import pins
from ci.checksums.registry import ENTRIES, Listed, Location

REPO_ROOT = Path(__file__).resolve().parents[4]
HASH = "a" * 64


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def entry_at(path: str) -> Listed:
    return Listed(
        name="tool",
        pin=Location(path, "tool_sha256"),
        version=Location(path, "tool_version"),
        file="tool-{version}.zip",
        manifest_url="https://example.invalid/{version}/SHA256SUMS",
    )


class TestReadValue:
    @pytest.mark.parametrize(
        "line",
        [
            pytest.param('tool_version: "1.2.3"', id="double-quoted"),
            pytest.param("tool_version: '1.2.3'", id="single-quoted"),
            pytest.param("tool_version: 1.2.3", id="bare"),
            pytest.param('tool_version: "1.2.3"   # bumped by Renovate', id="trailing-comment"),
            pytest.param("tool_version:    1.2.3", id="extra-space"),
        ],
    )
    def test_a_yaml_value_is_read_in_every_form_it_is_written(self, root, line):
        write(root, "defaults.yaml", f"---\nother: x\n{line}\nnext: y\n")
        assert pins.read_value(root, Location("defaults.yaml", "tool_version")) == "1.2.3"

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param("ARG TOOL_VERSION=1.2.3", id="bare"),
            pytest.param('ARG TOOL_VERSION="1.2.3"', id="double-quoted"),
            pytest.param("  ARG TOOL_VERSION='1.2.3'  ", id="indented-single-quoted"),
        ],
    )
    def test_a_dockerfile_arg_is_read_in_every_form_it_is_written(self, root, line):
        write(root, "app/Dockerfile", f"FROM scratch\n{line}\nRUN true\n")
        assert pins.read_value(root, Location("app/Dockerfile", "TOOL_VERSION")) == "1.2.3"

    def test_a_key_that_only_starts_with_the_name_is_not_it(self, root):
        write(root, "defaults.yaml", "tool_version_old: 0.0.1\ntool_version: 1.2.3\n")
        assert pins.read_value(root, Location("defaults.yaml", "tool_version")) == "1.2.3"

    def test_an_indented_key_is_not_a_top_level_one(self, root):
        write(root, "defaults.yaml", "group:\n  tool_version: 1.2.3\n")
        with pytest.raises(pins.PinError, match="no tool_version set to a plain value"):
            pins.read_value(root, Location("defaults.yaml", "tool_version"))

    def test_a_version_left_as_a_template_is_not_a_release_version(self, root):
        write(root, "defaults.yaml", f'tool_version: "{{{{ other }}}}"\ntool_sha256: {HASH}\n')
        with pytest.raises(pins.PinError, match="isn't a release version"):
            pins.read_pin(root, entry_at("defaults.yaml"))

    def test_a_key_set_twice_is_ambiguous(self, root):
        write(root, "defaults.yaml", "tool_version: 1.0.0\ntool_version: 2.0.0\n")
        with pytest.raises(pins.PinError, match="more than once"):
            pins.read_value(root, Location("defaults.yaml", "tool_version"))

    def test_a_file_that_is_not_there_is_an_error(self, root):
        with pytest.raises(pins.PinError, match=re.escape("can't read nowhere.yaml")):
            pins.read_value(root, Location("nowhere.yaml", "tool_version"))


class TestReadPin:
    def test_the_version_and_the_hash_come_back_together(self, root):
        write(root, "defaults.yaml", f'tool_version: "1.2.3"\ntool_sha256: "{HASH}"\n')
        assert pins.read_pin(root, entry_at("defaults.yaml")) == ("1.2.3", HASH)

    @pytest.mark.parametrize(
        "version",
        [
            pytest.param("../1.2.3", id="path-traversal"),
            pytest.param("1.2.3/../../x", id="slash"),
            pytest.param('"1.2.3 --flag"', id="space"),
            pytest.param("v1.2.3", id="leading-v"),
            pytest.param("1.2.3?x=1", id="query"),
            pytest.param("''", id="empty"),
        ],
    )
    def test_a_version_that_is_not_shaped_like_a_release_is_refused_before_it_reaches_a_url(self, root, version):
        write(root, "defaults.yaml", f"tool_version: {version}\ntool_sha256: {HASH}\n")
        with pytest.raises(pins.PinError, match="isn't a release version"):
            pins.read_pin(root, entry_at("defaults.yaml"))

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("A" * 64, id="upper-case"),
            pytest.param("a" * 63, id="short"),
            pytest.param("a" * 65, id="long"),
            pytest.param("sha256:" + "a" * 64, id="with-a-prefix"),
        ],
    )
    def test_a_hash_that_is_not_a_lower_case_sha256_is_refused(self, root, value):
        write(root, "defaults.yaml", f"tool_version: 1.2.3\ntool_sha256: {value}\n")
        with pytest.raises(pins.PinError, match="isn't a lower-case sha256"):
            pins.read_pin(root, entry_at("defaults.yaml"))


class TestDiscover:
    def test_a_yaml_pin_is_found_at_any_depth_and_as_a_list_item(self, root):
        write(root, "ansible/roles/a/defaults/main.yaml", f'a_sha256: "{HASH}"\n')
        write(root, "docker/app/compose.yaml", f"services:\n  x:\n    environment:\n      X_SHA256: {HASH}\n    args:\n      - Y_SHA256: {HASH}\n")
        assert [(p.path, p.name) for p in pins.discover(root)] == [
            ("ansible/roles/a/defaults/main.yaml", "a_sha256"),
            ("docker/app/compose.yaml", "X_SHA256"),
            ("docker/app/compose.yaml", "Y_SHA256"),
        ]

    def test_a_dockerfile_arg_is_found(self, root):
        write(root, "tools/app/Dockerfile", f"FROM scratch\nARG TOOL_SHA256={HASH}\n")
        assert pins.discover(root) == [pins.Found("tools/app/Dockerfile", "TOOL_SHA256", HASH)]

    def test_a_hash_written_into_a_task_is_found_under_a_name_that_no_entry_can_have(self, root):
        write(root, "ansible/roles/a/tasks/main.yaml", f'- ansible.builtin.get_url:\n    checksum: "sha256:{HASH}"\n')
        assert pins.discover(root) == [pins.Found("ansible/roles/a/tasks/main.yaml", "checksum:", HASH)]

    def test_a_task_that_reads_its_hash_from_a_variable_is_not_a_pin_itself(self, root):
        write(root, "ansible/roles/a/tasks/main.yaml", '- ansible.builtin.get_url:\n    checksum: "sha256:{{ a_sha256 }}"\n')
        assert pins.discover(root) == []

    @pytest.mark.parametrize(
        "rel",
        [
            pytest.param("docs/topics/example.yaml", id="docs-tree"),
            pytest.param("ansible/roles/a/files/script.py", id="python-file"),
            pytest.param("ansible/roles/a/files/notes.md", id="markdown-file"),
            pytest.param("ansible/.git/config.yaml", id="skipped-directory"),
            pytest.param("ansible/node_modules/p/x.yaml", id="node-modules"),
        ],
    )
    def test_files_outside_what_a_download_is_pinned_in_are_ignored(self, root, rel):
        write(root, rel, f"a_sha256: {HASH}\n")
        assert pins.discover(root) == []

    def test_a_hash_that_is_not_a_pin_is_ignored(self, root):
        write(root, "ansible/defaults.yaml", f"cert_fingerprint: {HASH}\na_sha256: not-a-hash\na_sha256_note: {HASH} extra\n")
        assert pins.discover(root) == []


class TestRealTree:
    """The repository's own pins against the registry."""

    def test_every_checksum_pin_in_the_repository_has_a_registry_entry(self, subtests):
        registered = {(entry.pin.path, entry.pin.name) for entry in ENTRIES}
        for found in pins.discover(REPO_ROOT):
            with subtests.test(pin=f"{found.path}: {found.name}"):
                assert (found.path, found.name) in registered, f"{found.path} pins {found.name} with no entry in ci/checksums/registry.py"

    def test_every_registry_entry_names_a_pin_that_is_in_the_repository(self, subtests):
        present = {(found.path, found.name): found.value for found in pins.discover(REPO_ROOT)}
        for entry in ENTRIES:
            with subtests.test(entry=entry.name):
                assert present.get((entry.pin.path, entry.pin.name)) == pins.read_pin(REPO_ROOT, entry)[1]

    def test_every_entrys_version_is_readable_in_the_shape_of_a_release(self, subtests):
        for entry in ENTRIES:
            with subtests.test(entry=entry.name):
                assert pins.VERSION.fullmatch(pins.read_pin(REPO_ROOT, entry)[0])

    def test_the_four_pins_the_decision_names_are_found(self):
        assert {found.name for found in pins.discover(REPO_ROOT)} == {
            "cd_agent_uv_sha256",
            "cd_agent_rclone_sha256",
            "openbao_cli_deb_sha256",
            "CODERABBIT_SHA256",
        }
