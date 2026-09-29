"""Tests for ci.gates.secrets_registry_rules: one case per rule, then the real registry.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.gates import secrets_registry_rules as rules
from utils.secrets_registry import load_registry

GOOD = {
    "session-key": {"format": "hex", "length": 32, "vault_scope": "hosts/services"},
    "request-id": {"format": "uuid4", "vault_scope": "hosts/all/shlink"},
    "api-token": {"format": "manual", "description": "d", "sensitive": True, "allow_blank": False, "vault_scope": "cloud_credentials/leaf"},
    "main-domain": {"format": "manual", "description": "The main domain"},
}


def broken(name: str, spec: dict[str, object]) -> list[str]:
    """The rule ids `spec` breaks when it is the only entry."""
    return [violation.rule for violation in rules.validate({name: spec})]


class EachRuleTests(unittest.TestCase):
    def test_a_registry_that_follows_every_rule_has_no_violations(self):
        self.assertEqual(rules.validate(GOOD), [])
        self.assertEqual(rules.validate({}), [])

    def test_name_must_be_kebab_case(self):
        for name in ("Session_Key", "session--key", "-session", "session-", "session key", "a/b", ""):
            with self.subTest(name=name):
                self.assertEqual(broken(name, {"format": "uuid4", "vault_scope": "hosts/play"}), ["name"])

    def test_an_unknown_key_is_refused_so_a_typo_cannot_move_an_entry(self):
        self.assertEqual(broken("a", {"format": "manual", "description": "d", "vault_scop": "hosts/play"}), ["unknown-key"])

    def test_format_must_be_hex_uuid4_or_manual(self):
        for spec in ({"description": "d"}, {"format": "base64", "description": "d"}, {"format": None}):
            with self.subTest(spec=spec):
                self.assertIn("format", broken("a", spec))

    def test_hex_requires_a_positive_integer_length(self):
        for length in ({}, {"length": 0}, {"length": -4}, {"length": "32"}, {"length": True}, {"length": 8.5}):
            with self.subTest(length=length):
                self.assertEqual(broken("a", {"format": "hex", "vault_scope": "hosts/play", **length}), ["length-required"])

    def test_other_formats_forbid_length(self):
        self.assertEqual(broken("a", {"format": "uuid4", "length": 32, "vault_scope": "hosts/play"}), ["length-forbidden"])
        self.assertEqual(broken("a", {"format": "manual", "length": 32, "description": "d"}), ["length-forbidden"])

    def test_generated_secrets_require_a_vault_scope(self):
        self.assertEqual(broken("a", {"format": "hex", "length": 32}), ["scope-required"])
        self.assertEqual(broken("a", {"format": "uuid4"}), ["scope-required"])

    def test_a_manual_secret_may_omit_the_scope(self):
        self.assertEqual(broken("a", {"format": "manual", "description": "d"}), [])

    def test_vault_scope_must_be_one_of_the_headers_shapes(self):
        for scope in (
            "",
            "hosts",
            "hosts/other",
            "hosts/all",
            "hosts/all/Caddy",
            "hosts/security/",
            "/hosts/security",
            "cloud_credentials/rotation",
            "secret/hosts/play",
            None,
            7,
        ):
            with self.subTest(scope=scope):
                self.assertEqual(broken("a", {"format": "uuid4", "vault_scope": scope}), ["scope-shape"])

    def test_every_shape_the_header_names_is_accepted(self):
        for scope in ("hosts/security", "hosts/services", "hosts/storage", "hosts/play", "hosts/all/caddy-acme", "hosts/all/step-ca", "cloud_credentials/leaf"):
            with self.subTest(scope=scope):
                self.assertEqual(broken("a", {"format": "uuid4", "vault_scope": scope}), [])

    def test_manual_requires_a_non_empty_description(self):
        for extra in ({}, {"description": ""}, {"description": "   "}, {"description": None}, {"description": 3}):
            with self.subTest(extra=extra):
                self.assertEqual(broken("a", {"format": "manual", **extra}), ["description-required"])

    def test_allow_blank_and_sensitive_are_valid_only_on_manual(self):
        for flag in ("allow_blank", "sensitive"):
            for spec in ({"format": "uuid4", "vault_scope": "hosts/play"}, {"format": "hex", "length": 8, "vault_scope": "hosts/play"}):
                with self.subTest(flag=flag, format=spec["format"]):
                    self.assertEqual(broken("a", {**spec, flag: True}), ["flag-manual-only"])

    def test_allow_blank_and_sensitive_must_be_booleans(self):
        for flag in ("allow_blank", "sensitive"):
            for value in ("true", "yes", 1, 0, None):
                with self.subTest(flag=flag, value=value):
                    self.assertEqual(broken("a", {"format": "manual", "description": "d", flag: value}), ["flag-boolean"])

    def test_every_violation_in_an_entry_is_reported_not_just_the_first(self):
        found = broken("Bad_Name", {"format": "hex", "vault_scop": "x", "sensitive": True})
        self.assertEqual(sorted(found), ["flag-manual-only", "length-required", "name", "scope-required", "unknown-key"])

    def test_violations_name_the_entry_and_come_in_entry_order(self):
        found = rules.validate({"ok": GOOD["main-domain"], "one": {"format": "uuid4"}, "two": {"format": "hex", "length": 8}})
        self.assertEqual([(v.name, v.rule) for v in found], [("one", "scope-required"), ("two", "scope-required")])


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "registry.yaml"

    def run_main(self, text: str | None) -> tuple[int, str, str]:
        if text is not None:
            self.path.write_text(text)
        out, err = io.StringIO(), io.StringIO()
        with patch.object(rules, "REGISTRY_PATH", self.path), redirect_stdout(out), redirect_stderr(err):
            code = rules.main()
        return code, out.getvalue(), err.getvalue()

    def test_passes_a_clean_registry(self):
        code, out, err = self.run_main("secrets_registry:\n  a: { format: uuid4, vault_scope: hosts/play }\n")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("follows the header's rules", out)

    def test_fails_and_names_each_violation_and_its_rule(self):
        code, _, err = self.run_main("secrets_registry:\n  a: { format: hex, length: 8 }\n  b: { format: manual }\n")
        self.assertEqual(code, 1)
        self.assertIn("::error::a:", err)
        self.assertIn("[scope-required]", err)
        self.assertIn("::error::b:", err)
        self.assertIn("[description-required]", err)
        self.assertIn("2 rule violation(s)", err)

    def test_fails_on_an_unreadable_registry(self):
        code, _, err = self.run_main(None)
        self.assertEqual(code, 1)
        self.assertIn("::error::can't read", err)

    def test_fails_on_a_repeated_name(self):
        code, _, err = self.run_main("secrets_registry:\n  a: { format: manual, description: d }\n  a: { format: manual, description: d }\n")
        self.assertEqual(code, 1)
        self.assertIn("duplicate key", err)


class RealRegistryTests(unittest.TestCase):
    def test_the_real_registry_follows_every_rule(self):
        self.assertEqual(rules.validate(load_registry()), [])

    def test_main_passes_on_the_real_registry(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(rules.main(), 0)


if __name__ == "__main__":
    unittest.main()
