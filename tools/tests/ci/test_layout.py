"""Where code lives (ADR 0064): the repo's layout rules, as tests.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS = REPO_ROOT / "tools"
GITHUB = REPO_ROOT / ".github"
# Where a workflow, composite action or pre-commit hook may name a module to run.
CALLERS = [*sorted((GITHUB / "workflows").glob("*.yml")), *sorted((GITHUB / "actions").glob("*/action.yml")), REPO_ROOT / ".config/.pre-commit-config.yaml"]
MODULE_RUN = re.compile(r"python3? -m ((?:ci|doc_scripts)(?:\.\w+)+)")


class LayoutTests(unittest.TestCase):
    def test_github_scripts_holds_no_python(self):
        self.assertEqual(sorted(p.name for p in (GITHUB / "scripts").rglob("*.py")), [])

    def test_no_test_reaches_into_dot_github_for_code(self):
        for path in sorted((TOOLS / "tests").rglob("*.py")):
            if path.name == Path(__file__).name:
                continue
            with self.subTest(test=path.relative_to(REPO_ROOT).as_posix()):
                self.assertNotIn(".github/scripts", path.read_text().replace("tools/doc_scripts", ""), "imports or runs code from .github/scripts")

    def test_no_caller_runs_a_python_file_from_dot_github(self):
        for caller in CALLERS:
            with self.subTest(caller=caller.relative_to(REPO_ROOT).as_posix()):
                self.assertNotRegex(caller.read_text(), r"python3?\s+\.github/scripts/\S+\.py")

    def test_every_module_a_caller_runs_exists(self):
        found = 0
        for caller in CALLERS:
            for module in MODULE_RUN.findall(caller.read_text()):
                found += 1
                with self.subTest(caller=caller.name, module=module):
                    self.assertTrue((TOOLS / (module.replace(".", "/") + ".py")).is_file(), f"tools/{module.replace('.', '/')}.py")
        self.assertGreater(found, 20)

    def test_every_package_under_tools_triggers_the_unit_tests(self):
        filters = yaml.safe_load((GITHUB / "detect-changes-filters.yml").read_text())["python_unit_tests"]
        for init in sorted(TOOLS.glob("*/__init__.py")):
            package = init.parent.name
            with self.subTest(package=package):
                self.assertIn(f"tools/{package}/**", filters)

    def test_package_names_do_not_shadow_the_standard_library(self):
        import sys

        for init in sorted(TOOLS.glob("*/__init__.py")):
            with self.subTest(package=init.parent.name):
                self.assertNotIn(init.parent.name, sys.stdlib_module_names)


if __name__ == "__main__":
    unittest.main()
