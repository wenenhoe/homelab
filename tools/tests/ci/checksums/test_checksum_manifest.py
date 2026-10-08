"""Tests for ci.checksums.manifest.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
from ci.checksums import manifest

HASH = "a" * 64
OTHER = "b" * 64


class TestParse:
    @pytest.mark.parametrize(
        ("line", "name", "listed"),
        [
            pytest.param(f"{HASH}  tool.zip", "tool.zip", HASH, id="two-spaces"),
            pytest.param(f"{HASH}  ./tool.zip", "tool.zip", HASH, id="dot-slash"),
            pytest.param(f"{HASH} *tool.zip", "tool.zip", HASH, id="binary-marker"),
            pytest.param(f"{HASH}\ttool.zip", "tool.zip", HASH, id="tab"),
            pytest.param(f"{HASH.upper()}  tool.zip", "tool.zip", HASH, id="upper-case-hash"),
            pytest.param(f"{HASH}  tool v1.zip  ", "tool v1.zip", HASH, id="name-with-a-space"),
        ],
    )
    def test_each_form_of_a_line_is_read(self, line, name, listed):
        assert manifest.parse(f"{line}\n") == {name: {listed}}

    def test_lines_that_are_not_a_hash_and_a_name_are_ignored(self):
        text = f"# a comment\n\n{HASH[:-1]}  short.zip\n{HASH}\nnot a line\n{HASH}  real.zip\n"
        assert manifest.parse(text) == {"real.zip": {HASH}}

    def test_a_name_listed_twice_keeps_both_hashes(self):
        assert manifest.parse(f"{HASH}  tool.zip\n{OTHER}  tool.zip\n") == {"tool.zip": {HASH, OTHER}}


class TestMismatch:
    def test_a_pin_equal_to_the_manifests_hash_for_the_file_is_no_mismatch(self):
        assert manifest.mismatch({"tool.zip": {HASH}}, "tool.zip", HASH) is None

    def test_a_pin_that_differs_names_the_hash_the_manifest_lists(self):
        message = manifest.mismatch({"tool.zip": {OTHER}}, "tool.zip", HASH)
        assert message == f"the pin is {HASH} but the manifest lists {OTHER} for tool.zip"

    def test_a_file_the_manifest_does_not_list_is_a_mismatch(self):
        assert manifest.mismatch({"other.zip": {HASH}}, "tool.zip", HASH) == "the manifest has no line for tool.zip"

    def test_a_hash_listed_only_for_another_file_does_not_satisfy_the_pin(self):
        assert manifest.mismatch({"tool.zip.sbom.json": {HASH}}, "tool.zip", HASH) == "the manifest has no line for tool.zip"

    def test_a_file_listed_twice_with_different_hashes_fails_even_when_one_is_the_pin(self):
        message = manifest.mismatch({"tool.zip": {HASH, OTHER}}, "tool.zip", HASH)
        assert message == f"the pin is {HASH} but the manifest lists {HASH}, {OTHER} for tool.zip"

    def test_a_file_listed_twice_with_the_same_hash_is_one_line(self):
        assert manifest.mismatch(manifest.parse(f"{HASH}  tool.zip\n{HASH}  ./tool.zip\n"), "tool.zip", HASH) is None
