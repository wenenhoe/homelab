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
    "session-key": {"source": "hex", "length": 32, "store": "openbao", "scope": "hosts/services"},
    "request-id": {"source": "uuid4", "store": "openbao", "scope": "hosts/all/shlink"},
    "api-token": {"source": "manual", "description": "d", "sensitive": True, "allow_blank": False, "store": "openbao", "scope": "cloud_credentials/leaf"},
    "main-domain": {"source": "manual", "description": "The main domain", "store": "controller_file"},
}
OPENBAO = {"store": "openbao", "scope": "hosts/play"}
FILE_CACHE = {"store": "controller_file"}


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
                self.assertEqual(broken(name, {"source": "uuid4", **OPENBAO}), ["name"])

    def test_an_unknown_key_is_refused_so_a_typo_cannot_change_an_entry(self):
        self.assertEqual(broken("a", {"source": "manual", "description": "d", "store": "openbao", "scope": "hosts/play", "scop": "x"}), ["unknown-key"])

    def test_the_old_field_names_are_unknown_keys(self):
        self.assertIn("unknown-key", broken("a", {"format": "uuid4", "source": "uuid4", **OPENBAO}))
        self.assertIn("unknown-key", broken("a", {"source": "uuid4", "vault_scope": "hosts/play", **OPENBAO}))

    def test_source_must_be_hex_uuid4_or_manual(self):
        for spec in ({**OPENBAO}, {"source": "base64", **OPENBAO}, {"source": None, **OPENBAO}):
            with self.subTest(spec=spec):
                self.assertIn("source", broken("a", spec))

    def test_store_is_required_and_must_be_openbao_or_controller_file(self):
        for extra in ({}, {"store": "vault"}, {"store": None}, {"store": ""}, {"store": "OpenBao"}):
            with self.subTest(extra=extra):
                self.assertIn("store", broken("a", {"source": "manual", "description": "d", **extra}))

    def test_hex_requires_a_positive_integer_length(self):
        for length in ({}, {"length": 0}, {"length": -4}, {"length": "32"}, {"length": True}, {"length": 8.5}):
            with self.subTest(length=length):
                self.assertEqual(broken("a", {"source": "hex", **OPENBAO, **length}), ["length-required"])

    def test_other_sources_forbid_length(self):
        self.assertEqual(broken("a", {"source": "uuid4", "length": 32, **OPENBAO}), ["length-forbidden"])
        self.assertEqual(broken("a", {"source": "manual", "length": 32, "description": "d", **FILE_CACHE}), ["length-forbidden"])

    def test_store_openbao_requires_a_scope(self):
        self.assertEqual(broken("a", {"source": "manual", "description": "d", "store": "openbao"}), ["scope-required"])
        self.assertEqual(broken("a", {"source": "uuid4", "store": "openbao"}), ["scope-required"])

    def test_store_controller_file_forbids_a_scope(self):
        self.assertEqual(broken("a", {"source": "manual", "description": "d", "store": "controller_file", "scope": "hosts/play"}), ["scope-forbidden"])

    def test_generated_sources_require_store_openbao(self):
        self.assertEqual(broken("a", {"source": "hex", "length": 32, **FILE_CACHE}), ["generated-store"])
        self.assertEqual(broken("a", {"source": "uuid4", **FILE_CACHE}), ["generated-store"])

    def test_a_manual_secret_may_be_stored_in_either_place(self):
        self.assertEqual(broken("a", {"source": "manual", "description": "d", **FILE_CACHE}), [])
        self.assertEqual(broken("a", {"source": "manual", "description": "d", **OPENBAO}), [])

    def test_scope_must_be_one_of_the_headers_shapes(self):
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
                self.assertEqual(broken("a", {"source": "uuid4", "store": "openbao", "scope": scope}), ["scope-shape"])

    def test_every_shape_the_header_names_is_accepted(self):
        for scope in ("hosts/security", "hosts/services", "hosts/storage", "hosts/play", "hosts/all/caddy-acme", "hosts/all/step-ca", "cloud_credentials/leaf"):
            with self.subTest(scope=scope):
                self.assertEqual(broken("a", {"source": "uuid4", "store": "openbao", "scope": scope}), [])

    def test_manual_requires_a_non_empty_description(self):
        for extra in ({}, {"description": ""}, {"description": "   "}, {"description": None}, {"description": 3}):
            with self.subTest(extra=extra):
                self.assertEqual(broken("a", {"source": "manual", **FILE_CACHE, **extra}), ["description-required"])

    def test_allow_blank_and_sensitive_are_valid_only_on_manual(self):
        for flag in ("allow_blank", "sensitive"):
            for spec in ({"source": "uuid4", **OPENBAO}, {"source": "hex", "length": 8, **OPENBAO}):
                with self.subTest(flag=flag, source=spec["source"]):
                    self.assertEqual(broken("a", {**spec, flag: True}), ["flag-manual-only"])

    def test_allow_blank_and_sensitive_must_be_booleans(self):
        for flag in ("allow_blank", "sensitive"):
            for value in ("true", "yes", 1, 0, None):
                with self.subTest(flag=flag, value=value):
                    self.assertEqual(broken("a", {"source": "manual", "description": "d", **FILE_CACHE, flag: value}), ["flag-boolean"])

    def test_every_violation_in_an_entry_is_reported_not_just_the_first(self):
        found = broken("Bad_Name", {"source": "hex", "scop": "x", "sensitive": True, "store": "controller_file"})
        self.assertEqual(sorted(found), ["flag-manual-only", "generated-store", "length-required", "name", "unknown-key"])

    def test_violations_name_the_entry_and_come_in_entry_order(self):
        found = rules.validate({"ok": GOOD["main-domain"], "one": {"source": "uuid4", "store": "openbao"}, "two": {"source": "hex", "length": 8, **FILE_CACHE}})
        self.assertEqual([(v.name, v.rule) for v in found], [("one", "scope-required"), ("two", "generated-store")])


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
        code, out, err = self.run_main("secrets_registry:\n  a: { source: uuid4, store: openbao, scope: hosts/play }\n")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("follows the header's rules", out)

    def test_fails_and_names_each_violation_and_its_rule(self):
        code, _, err = self.run_main("secrets_registry:\n  a: { source: hex, length: 8, store: openbao }\n  b: { source: manual, store: controller_file }\n")
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
        code, _, err = self.run_main(
            "secrets_registry:\n"
            "  a: { source: manual, description: d, store: controller_file }\n"
            "  a: { source: manual, description: d, store: controller_file }\n"
        )
        self.assertEqual(code, 1)
        self.assertIn("duplicate key", err)


class RealRegistryTests(unittest.TestCase):
    def test_the_real_registry_follows_every_rule(self):
        self.assertEqual(rules.validate(load_registry()), [])

    def test_main_passes_on_the_real_registry(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(rules.main(), 0)

    def test_every_real_entry_states_its_store(self):
        self.assertTrue(all(spec.get("store") in ("openbao", "controller_file") for spec in load_registry().values()))


if __name__ == "__main__":
    unittest.main()
