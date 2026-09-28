"""Tests for ci.json5, the JSON5 subset reader.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ci import json5

REPO_ROOT = Path(__file__).resolve().parents[3]


class ParseTests(unittest.TestCase):
    def test_plain_json_is_read_as_json(self):
        text = '{"a": [1, 2.5, -3, 1e2, true, false, null, "x"], "b": {"c": "d"}}'
        self.assertEqual(json5.loads(text), json.loads(text))

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
        self.assertEqual(json5.loads(text), {"key": "single", "quoted": ["a", "b"], "nested": {"inner": 1}})

    def test_comment_markers_inside_strings_are_kept(self):
        self.assertEqual(
            json5.loads('{u: "https://example.com/a//b", c: "/* not a comment */"}'), {"u": "https://example.com/a//b", "c": "/* not a comment */"}
        )

    def test_string_escapes(self):
        self.assertEqual(json5.loads(r'"a\\s\n\t\"q\" \u0041 \/"'), 'a\\s\n\t"q" A /')

    def test_regex_backslashes_survive_the_way_renovate_config_writes_them(self):
        self.assertEqual(json5.loads(r'["rclone/rclone:(?<v>[0-9.]+)", "/^\\.github\\/x$/"]'), ["rclone/rclone:(?<v>[0-9.]+)", r"/^\.github\/x$/"])

    def test_identifiers_with_dollar_and_underscore_and_empty_containers(self):
        self.assertEqual(json5.loads("{$a: {}, _b: []}"), {"$a": {}, "_b": []})

    def test_a_document_that_is_only_a_comment_after_the_value_is_fine(self):
        self.assertEqual(json5.loads("[1] // done\n"), [1])


class RejectTests(unittest.TestCase):
    def test_unsupported_or_malformed_input_is_an_error(self):
        for text in (
            "{a: 1",
            "[1 2]",
            '{"a" 1}',
            "{a: Infinity}",
            "{a: NaN}",
            "{a: 0x10}",
            '"unterminated',
            "/* unterminated",
            "[1] extra",
            "",
            '"a\\\nb"',
            r'"\u12"',
        ):
            with self.subTest(text=text), self.assertRaises(json5.Json5Error):
                json5.loads(text)

    def test_the_error_says_which_line(self):
        with self.assertRaisesRegex(json5.Json5Error, r"line 3"):
            json5.loads("{\n a: 1,\n b: ?\n}")


class RealConfigTests(unittest.TestCase):
    def test_the_real_renovate_config_parses_and_has_custom_managers(self):
        config = json5.loads((REPO_ROOT / ".github/renovate.json5").read_text())
        self.assertIsInstance(config, dict)
        self.assertTrue(config["customManagers"])
        self.assertEqual(config["timezone"], "Asia/Singapore")


if __name__ == "__main__":
    unittest.main()
