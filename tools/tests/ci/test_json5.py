"""Tests for ci.json5, the JSON5 subset reader.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ci import json5

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestParse:
    def test_plain_json_is_read_as_json(self):
        text = '{"a": [1, 2.5, -3, 1e2, true, false, null, "x"], "b": {"c": "d"}}'
        assert json5.loads(text) == json.loads(text)

    def test_comments_unquoted_keys_single_quotes_and_trailing_commas(self):
        text = """
        // a line comment
        {
          key: 'single',   /* a block
                              comment */
          "quoted": ["a", "b",],
          nested: { inner: 1, },
        }
        """
        assert json5.loads(text) == {"key": "single", "quoted": ["a", "b"], "nested": {"inner": 1}}

    def test_comment_markers_inside_strings_are_kept(self):
        assert json5.loads('{u: "https://example.com/a//b", c: "/* not a comment */"}') == {"u": "https://example.com/a//b", "c": "/* not a comment */"}

    def test_string_escapes(self):
        assert json5.loads(r'"a\\s\n\t\"q\" \u0041 \/"') == 'a\\s\n\t"q" A /'

    def test_regex_backslashes_survive_the_way_renovate_config_writes_them(self):
        assert json5.loads(r'["rclone/rclone:(?<v>[0-9.]+)", "/^\\.github\\/x$/"]') == ["rclone/rclone:(?<v>[0-9.]+)", r"/^\.github\/x$/"]

    def test_identifiers_with_dollar_and_underscore_and_empty_containers(self):
        assert json5.loads("{$a: {}, _b: []}") == {"$a": {}, "_b": []}

    def test_a_document_that_is_only_a_comment_after_the_value_is_fine(self):
        assert json5.loads("[1] // done\n") == [1]


class TestReject:
    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("{a: 1", id="unclosed-object"),
            pytest.param("[1 2]", id="missing-comma"),
            pytest.param('{"a" 1}', id="missing-colon"),
            pytest.param("{a: Infinity}", id="infinity"),
            pytest.param("{a: NaN}", id="nan"),
            pytest.param("{a: 0x10}", id="hex-number"),
            pytest.param('"unterminated', id="unterminated-string"),
            pytest.param("/* unterminated", id="unterminated-block-comment"),
            pytest.param("[1] extra", id="trailing-garbage"),
            pytest.param("", id="empty-input"),
            pytest.param('"a\\\nb"', id="line-continuation-in-string"),
            pytest.param(r'"\u12"', id="short-unicode-escape"),
        ],
    )
    def test_unsupported_or_malformed_input_is_an_error(self, text):
        with pytest.raises(json5.Json5Error):
            json5.loads(text)

    def test_the_error_says_which_line(self):
        with pytest.raises(json5.Json5Error, match=r"line 3"):
            json5.loads("{\n a: 1,\n b: ?\n}")


class TestRealConfig:
    def test_the_real_renovate_config_parses_and_has_custom_managers(self):
        config = json5.loads((REPO_ROOT / ".github/renovate.json5").read_text())
        assert isinstance(config, dict)
        assert config["customManagers"]
        assert config["timezone"] == "Asia/Singapore"
