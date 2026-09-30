"""Tests for ci.gates.app_catalog_rules: one case per rule, then the real catalog.

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

from ci.gates import app_catalog_rules as rules
from utils.app_catalog import CATALOG_KEY, load_catalog

GOOD = {
    "web": {
        "volumes": [{"name": "data"}, {"name": "config"}],
        "configs": [{"src": "env.j2", "dest": ".env"}],
        "backup": {"volumes": ["data"], "stop_during_backup": True},
        "routes": {"default": {"upstream": "web:8080"}, "admin": {"upstream": "web:9000", "auth": False}},
    },
    "agent": {"volumes": [{"name": "data"}]},
    "bare": {},
}


def broken(app: dict[str, object]) -> list[str]:
    """The rule ids `app` breaks when it is the only entry."""
    return [violation.rule for violation in rules.validate({"a": app})]


class EachRuleTests(unittest.TestCase):
    def test_a_catalog_that_follows_every_rule_has_no_violations(self):
        self.assertEqual(rules.validate(GOOD), [])
        self.assertEqual(rules.validate({}), [])

    def test_backup_volumes_must_be_declared_volumes(self):
        self.assertEqual(broken({"volumes": [{"name": "data"}], "backup": {"volumes": ["data", "cache"]}}), ["backup-volume"])

    def test_backup_volumes_with_no_volumes_at_all_are_undeclared(self):
        self.assertEqual(broken({"backup": {"volumes": ["data"]}}), ["backup-volume"])
        self.assertEqual(broken({"volumes": [], "backup": {"volumes": ["data"]}}), ["backup-volume"])

    def test_every_undeclared_backup_volume_is_reported(self):
        found = rules.validate({"a": {"volumes": [{"name": "x"}], "backup": {"volumes": ["p", "x", "q"]}}})
        self.assertEqual([(v.rule, "`p`" in v.message, "`q`" in v.message) for v in found], [("backup-volume", True, False), ("backup-volume", False, True)])

    def test_a_backup_with_no_volumes_key_or_an_empty_list_is_fine(self):
        self.assertEqual(broken({"backup": {"stop_during_backup": True}}), [])
        self.assertEqual(broken({"volumes": [{"name": "data"}], "backup": {"volumes": []}}), [])

    def test_every_route_must_name_an_upstream(self):
        for route in ({}, {"auth": False}, {"upstream": ""}, {"upstream": "  "}, {"upstream": None}, {"upstream": 8080}):
            with self.subTest(route=route):
                self.assertEqual(broken({rules.ROUTES_KEY: {"default": route}}), ["route-upstream"])

    def test_a_missing_upstream_names_its_route(self):
        found = rules.validate({"a": {rules.ROUTES_KEY: {"web": {"upstream": "a:1"}, "admin": {"auth": False}}}})
        self.assertEqual([(v.rule, "`admin`" in v.message) for v in found], [("route-upstream", True)])

    def test_a_route_map_under_the_old_key_is_refused(self):
        self.assertEqual(broken({rules.LEGACY_ROUTES_KEY: {"default": {"upstream": "web:80"}}}), ["legacy-route-key"])
        self.assertEqual(
            broken({rules.LEGACY_ROUTES_KEY: {"default": {"upstream": "web:80"}}, rules.ROUTES_KEY: {"default": {"upstream": "web:80"}}}), ["legacy-route-key"]
        )

    def test_the_old_key_holding_something_else_is_not_a_route_map(self):
        self.assertEqual(broken({rules.LEGACY_ROUTES_KEY: {}}), [])
        self.assertEqual(broken({rules.LEGACY_ROUTES_KEY: {"volumes": []}}), [])

    def test_an_app_with_no_routes_is_fine(self):
        self.assertEqual(broken({"volumes": [{"name": "data"}]}), [])
        self.assertEqual(broken({rules.ROUTES_KEY: {}}), [])

    def test_wrong_shapes_are_reported_instead_of_crashing(self):
        cases = {
            "volumes-shape": [{"volumes": "data"}, {"volumes": ["data"]}, {"volumes": [{"size": 1}]}, {"volumes": [{"name": ""}]}],
            "backup-shape": [{"backup": ["data"]}, {"backup": {"volumes": "data"}}, {"backup": {"volumes": [1]}}, {"backup": {"volumes": [""]}}],
            "routes-shape": [{rules.ROUTES_KEY: ["web:80"]}, {rules.ROUTES_KEY: {"default": "web:80"}}],
        }
        for rule, apps in cases.items():
            for app in apps:
                with self.subTest(rule=rule, app=app):
                    self.assertEqual(broken(app), [rule])

    def test_malformed_volumes_do_not_also_fail_the_subset_check(self):
        self.assertEqual(broken({"volumes": "data", "backup": {"volumes": ["data"]}}), ["volumes-shape"])

    def test_every_violation_in_an_app_is_reported_not_just_the_first(self):
        found = broken({"volumes": [{"name": "data"}], "backup": {"volumes": ["cache"]}, rules.ROUTES_KEY: {"default": {}}})
        self.assertEqual(sorted(found), ["backup-volume", "route-upstream"])

    def test_violations_name_the_app_and_come_in_app_order(self):
        found = rules.validate({"ok": GOOD["web"], "one": {rules.ROUTES_KEY: {"r": {}}}, "two": {"backup": {"volumes": ["x"]}}})
        self.assertEqual([(v.name, v.rule) for v in found], [("one", "route-upstream"), ("two", "backup-volume")])


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "catalog.yaml"

    def run_main(self, text: str | None) -> tuple[int, str, str]:
        if text is not None:
            self.path.write_text(text)
        out, err = io.StringIO(), io.StringIO()
        with patch.object(rules, "CATALOG_PATH", self.path), redirect_stdout(out), redirect_stderr(err):
            code = rules.main()
        return code, out.getvalue(), err.getvalue()

    def test_passes_a_clean_catalog(self):
        code, out, err = self.run_main(f"{CATALOG_KEY}:\n  a:\n    volumes: [{{ name: data }}]\n    backup: {{ volumes: [data] }}\n")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("every app follows the catalog rules", out)

    def test_fails_and_names_each_violation_and_its_rule(self):
        code, _, err = self.run_main(
            f"{CATALOG_KEY}:\n  a:\n    backup: {{ volumes: [data] }}\n  b:\n    {rules.ROUTES_KEY}:\n      default: {{ auth: false }}\n"
        )
        self.assertEqual(code, 1)
        self.assertIn("::error::a:", err)
        self.assertIn("[backup-volume]", err)
        self.assertIn("::error::b:", err)
        self.assertIn("[route-upstream]", err)
        self.assertIn("2 rule violation(s)", err)

    def test_fails_on_an_unreadable_catalog(self):
        code, _, err = self.run_main(None)
        self.assertEqual(code, 1)
        self.assertIn("::error::can't read", err)

    def test_fails_on_a_repeated_app_name(self):
        code, _, err = self.run_main(f"{CATALOG_KEY}:\n  a: {{}}\n  a: {{}}\n")
        self.assertEqual(code, 1)
        self.assertIn("duplicate key", err)


class RealCatalogTests(unittest.TestCase):
    def test_the_real_catalog_follows_every_rule(self):
        self.assertEqual(rules.validate(load_catalog()), [])

    def test_main_passes_on_the_real_catalog(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(rules.main(), 0)


if __name__ == "__main__":
    unittest.main()
