"""The CI modules workflows run on the runner's own python3 stay standard-library only.

Those jobs install no dependencies: the build workflows resolve tags in jobs
that hold a package-write token, the boot test and the Renovate check run in
jobs with nothing else to set up, and a pre-commit hook runs check-pins with
no extra packages. So these files may import only the standard library and
each other, and must parse on an older Python than the repo's own.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CI = REPO_ROOT / "tools/ci"
BARE_PYTHON = (
    "__init__.py",
    "output.py",
    "proc.py",
    "images/__init__.py",
    "images/registry.py",
    "images/build.py",
    "gates/__init__.py",
    "gates/compose_health.py",
    "gates/renovate_window.py",
    "gates/matrix_gate.py",
    "scan/__init__.py",
    "scan/trivy_config.py",
)


def _imported_modules(tree: ast.AST) -> list[str]:
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            modules.append(node.module or "")
    return modules


class StdlibOnlyTests(unittest.TestCase):
    def test_imports_are_standard_library_or_ci_only(self):
        for name in BARE_PYTHON:
            tree = ast.parse((CI / name).read_text(), feature_version=(3, 10))
            for module in _imported_modules(tree):
                top = module.split(".")[0]
                with self.subTest(file=name, module=module):
                    self.assertTrue(top in sys.stdlib_module_names or top == "ci", f"{name} imports {module}")

    def test_every_listed_file_exists(self):
        for name in BARE_PYTHON:
            with self.subTest(file=name):
                self.assertTrue((CI / name).is_file())

    def test_the_workflows_run_these_modules_with_plain_python3(self):
        for workflow, module in (
            ("_compose-boot-test.yml", "ci.gates.compose_health"),
            ("renovate.yml", "ci.gates.renovate_window"),
            ("build-caddy-image.yml", "ci.images.registry"),
            ("pr-checks.yml", "ci.gates.matrix_gate"),
            ("_trivy-scan.yml", "ci.scan.trivy_config"),
        ):
            with self.subTest(module=module):
                text = (REPO_ROOT / ".github/workflows" / workflow).read_text()
                self.assertIn(f"python3 -m {module}", text)
                self.assertNotIn(f"uv run python -m {module}", text)


if __name__ == "__main__":
    unittest.main()
