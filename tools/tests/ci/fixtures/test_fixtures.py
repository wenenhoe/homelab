"""Tests for ci.fixtures: the secrets-registry loader and the two fixture writers.

Most cases build a scratch repo holding a small registry; RealRegistryTests
run the same code over the real secrets_registry.yaml (writing into a
temporary tree, never into ansible/files/secrets), and RealWorkflowTests hold
the deploy-ordering job's steps to what the code and the gate module expect.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.fixtures import preseed_manual_secrets as pre
from ci.fixtures import secrets_registry as sr
from ci.fixtures import strip_vault_scope as strip
from ci.gates import deploy_ordering

REPO_ROOT = sr.REPO_ROOT

REGISTRY = {
    "cf-token": {"format": "manual", "description": "d", "sensitive": True, "vault_scope": "hosts/all"},
    "beszel-key": {"format": "manual", "allow_blank": True, "vault_scope": "hosts/play"},
    "main-domain": {"format": "manual"},
    "session-key": {"format": "hex", "length": 32, "vault_scope": "hosts/all"},
    "request-id": {"format": "uuid4"},
}


class Scratch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def write_registry(self, registry: object = None, text: str | None = None) -> None:
        path = self.root / sr.REGISTRY_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text is not None else yaml.safe_dump({"secrets_registry": REGISTRY if registry is None else registry}))


class LoadRegistryTests(Scratch):
    def test_returns_the_registry_mapping(self):
        self.write_registry()
        self.assertEqual(sr.load_registry(self.root), REGISTRY)

    def test_missing_file_invalid_yaml_and_wrong_shape_are_errors(self):
        with self.assertRaisesRegex(sr.RegistryError, "can't read"):
            sr.load_registry(self.root)
        for text in ("a: [", "[]", "other: {}", "secrets_registry: []", "secrets_registry:\n  x: notamapping\n", ""):
            self.write_registry(text=text)
            with self.subTest(text=text), self.assertRaises(sr.RegistryError):
                sr.load_registry(self.root)


class ManualValuesTests(unittest.TestCase):
    def test_only_manual_entries_get_a_value(self):
        self.assertEqual(set(pre.manual_values(REGISTRY)), {"cf-token", "beszel-key", "main-domain"})

    def test_allow_blank_entries_get_an_empty_string_and_the_rest_a_traceable_dummy(self):
        values = pre.manual_values(REGISTRY)
        self.assertEqual(values["beszel-key"], "")
        self.assertEqual(values["cf-token"], "ci-dummy-cf-token")
        self.assertEqual(values["main-domain"], "ci-dummy-main-domain")

    def test_allow_blank_false_or_missing_is_not_blank(self):
        values = pre.manual_values({"a": {"format": "manual", "allow_blank": False}, "b": {"format": "manual"}})
        self.assertEqual(values, {"a": "ci-dummy-a", "b": "ci-dummy-b"})

    def test_a_key_that_is_not_a_plain_file_name_is_refused(self):
        for key in ("../escape", "a/b", "/abs", "..", ".", ""):
            with self.subTest(key=key), self.assertRaisesRegex(sr.RegistryError, "can't be used as a file name"):
                pre.manual_values({key: {"format": "manual"}})

    def test_an_unsafe_key_on_a_non_manual_entry_is_not_a_file_and_is_ignored(self):
        self.assertEqual(pre.manual_values({"../x": {"format": "hex"}}), {})


class PreseedTests(Scratch):
    def test_writes_one_file_per_manual_secret_with_exact_contents(self):
        self.write_registry()
        written, secrets_dir = pre.preseed(self.root)
        self.assertEqual(written, 3)
        self.assertEqual(secrets_dir, self.root / pre.SECRETS_RELATIVE)
        self.assertEqual(sorted(p.name for p in secrets_dir.iterdir()), ["beszel-key", "cf-token", "main-domain"])
        self.assertEqual((secrets_dir / "beszel-key").read_bytes(), b"")
        self.assertEqual((secrets_dir / "cf-token").read_bytes(), b"ci-dummy-cf-token")

    def test_overwrites_an_existing_file_and_keeps_unrelated_ones(self):
        self.write_registry()
        secrets_dir = self.root / pre.SECRETS_RELATIVE
        secrets_dir.mkdir(parents=True)
        (secrets_dir / "cf-token").write_text("stale")
        (secrets_dir / "unrelated").write_text("keep")
        pre.preseed(self.root)
        self.assertEqual((secrets_dir / "cf-token").read_text(), "ci-dummy-cf-token")
        self.assertEqual((secrets_dir / "unrelated").read_text(), "keep")

    def test_a_registry_with_no_manual_entries_writes_nothing(self):
        self.write_registry({"a": {"format": "hex"}})
        written, secrets_dir = pre.preseed(self.root)
        self.assertEqual(written, 0)
        self.assertEqual(list(secrets_dir.iterdir()), [])

    def test_an_unsafe_key_writes_nothing_at_all(self):
        self.write_registry({"ok": {"format": "manual"}, "../bad": {"format": "manual"}})
        with self.assertRaises(sr.RegistryError):
            pre.preseed(self.root)
        self.assertFalse((self.root / pre.SECRETS_RELATIVE / "ok").exists())

    def test_main_prints_the_summary_and_reports_a_bad_registry_as_a_failure(self):
        self.write_registry()
        out = io.StringIO()
        with patch.object(pre, "REPO_ROOT", self.root), redirect_stdout(out):
            self.assertEqual(pre.main(), 0)
        self.assertIn("Pre-seeded 3 manual secrets", out.getvalue())
        self.write_registry(text="[]")
        err = io.StringIO()
        with patch.object(pre, "REPO_ROOT", self.root), redirect_stderr(err):
            self.assertEqual(pre.main(), 1)
        self.assertIn("::error::", err.getvalue())


class StripVaultScopeTests(Scratch):
    def test_removes_vault_scope_and_keeps_every_other_field(self):
        stripped = strip.strip_vault_scope(REGISTRY)
        self.assertNotIn("vault_scope", json.dumps(stripped))
        self.assertEqual(stripped["cf-token"], {"format": "manual", "description": "d", "sensitive": True})
        self.assertEqual(stripped["session-key"], {"format": "hex", "length": 32})
        self.assertEqual(set(stripped), set(REGISTRY))

    def test_does_not_mutate_its_input(self):
        original = json.loads(json.dumps(REGISTRY))
        strip.strip_vault_scope(REGISTRY)
        self.assertEqual(REGISTRY, original)

    def test_main_writes_json_under_a_secrets_registry_key_that_ansible_can_load(self):
        self.write_registry()
        target = self.root / "out.json"
        out = io.StringIO()
        with patch.object(strip, "REPO_ROOT", self.root), redirect_stdout(out):
            self.assertEqual(strip.main([str(target)]), 0)
        self.assertEqual(json.loads(target.read_text()), {"secrets_registry": strip.strip_vault_scope(REGISTRY)})
        self.assertIn("Wrote 5 entries", out.getvalue())

    def test_main_reports_a_bad_registry_without_writing(self):
        target = self.root / "out.json"
        err = io.StringIO()
        with patch.object(strip, "REPO_ROOT", self.root), redirect_stderr(err):
            self.assertEqual(strip.main([str(target)]), 1)
        self.assertFalse(target.exists())

    def test_main_requires_an_output_path(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            strip.main([])
        self.assertEqual(raised.exception.code, 2)


class RealRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = sr.load_registry(REPO_ROOT)

    def test_every_manual_entry_is_seeded_and_no_other(self):
        manual = {key for key, spec in self.registry.items() if spec.get("format") == "manual"}
        self.assertTrue(manual)
        self.assertEqual(set(pre.manual_values(self.registry)), manual)

    def test_the_real_registry_seeds_into_a_temporary_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / sr.REGISTRY_RELATIVE
            target.parent.mkdir(parents=True)
            target.write_text((REPO_ROOT / sr.REGISTRY_RELATIVE).read_text())
            written, secrets_dir = pre.preseed(root)
            self.assertEqual(written, len(list(secrets_dir.iterdir())))
            blank = {key for key, spec in self.registry.items() if spec.get("format") == "manual" and spec.get("allow_blank")}
            self.assertTrue(blank)
            for key in blank:
                self.assertEqual((secrets_dir / key).read_text(), "", key)

    def test_stripping_the_real_registry_keeps_every_entry_and_drops_only_vault_scope(self):
        stripped = strip.strip_vault_scope(self.registry)
        self.assertEqual(set(stripped), set(self.registry))
        for key, spec in self.registry.items():
            with self.subTest(key=key):
                self.assertEqual(stripped[key], {field: value for field, value in spec.items() if field != "vault_scope"})

    def test_the_real_registry_has_entries_with_a_vault_scope_to_strip(self):
        self.assertTrue(any("vault_scope" in spec for spec in self.registry.values()))


class RealWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/pr-checks.yml").read_text())
        cls.steps = workflow["jobs"]["deploy-ordering-check"]["steps"]

    def step(self, module: str) -> dict[str, str]:
        return next(step for step in self.steps if module in step.get("run", ""))

    def test_the_steps_run_the_modules_from_tools_under_uv(self):
        for module in ("ci.fixtures.preseed_manual_secrets", "ci.fixtures.strip_vault_scope"):
            with self.subTest(module=module):
                step = self.step(module)
                self.assertTrue(step["run"].startswith(f"uv run python -m {module}"))
                self.assertEqual(step["working-directory"], "tools")

    def test_the_registry_override_path_matches_what_the_gate_module_passes_to_ansible(self):
        argument = self.step("ci.fixtures.strip_vault_scope")["run"].split()[-1]
        self.assertEqual(deploy_ordering.REGISTRY_OVERRIDE, f"@{argument}")

    def test_both_fixtures_run_before_the_playbooks(self):
        names = [step["run"] for step in self.steps if "run" in step]
        order = {
            module: next(i for i, run in enumerate(names) if module in run)
            for module in ("preseed_manual_secrets", "strip_vault_scope", "ci.gates.deploy_ordering deploy")
        }
        self.assertLess(order["preseed_manual_secrets"], order["ci.gates.deploy_ordering deploy"])
        self.assertLess(order["strip_vault_scope"], order["ci.gates.deploy_ordering deploy"])

    def test_the_job_reruns_when_a_fixture_changes(self):
        filters = yaml.safe_load((REPO_ROOT / ".github/detect-changes-filters.yml").read_text())
        self.assertIn("tools/ci/fixtures/**", filters["deploy_ordering"])


if __name__ == "__main__":
    unittest.main()
