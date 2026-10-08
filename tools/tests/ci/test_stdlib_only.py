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
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CI = REPO_ROOT / "tools/ci"
BARE_PYTHON = (
    "__init__.py",
    "json5.py",
    "output.py",
    "proc.py",
    "checksums/__init__.py",
    "checksums/registry.py",
    "checksums/pins.py",
    "checksums/manifest.py",
    "images/__init__.py",
    "images/registry.py",
    "images/build.py",
    "images/remote.py",
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


class TestStdlibOnly:
    @pytest.mark.parametrize("name", BARE_PYTHON)
    def test_imports_are_standard_library_or_ci_only(self, name, subtests):
        tree = ast.parse((CI / name).read_text(), feature_version=(3, 10))
        for module in _imported_modules(tree):
            top = module.split(".")[0]
            with subtests.test(module=module):
                assert top in sys.stdlib_module_names or top == "ci", f"{name} imports {module}"

    @pytest.mark.parametrize("name", BARE_PYTHON)
    def test_every_listed_file_exists(self, name):
        assert (CI / name).is_file()

    @pytest.mark.parametrize(
        ("workflow", "module"),
        [
            pytest.param("_compose-boot-test.yml", "ci.gates.compose_health", id="compose_health"),
            pytest.param("renovate.yml", "ci.gates.renovate_window", id="renovate_window"),
            pytest.param("build-caddy-image.yml", "ci.images.registry", id="registry"),
            pytest.param("check-image-tags.yml", "ci.images.remote", id="remote"),
            pytest.param("pr-checks.yml", "ci.gates.matrix_gate", id="matrix_gate"),
            pytest.param("_trivy-scan.yml", "ci.scan.trivy_config", id="trivy_config"),
        ],
    )
    def test_the_workflows_run_these_modules_with_plain_python3(self, workflow, module):
        text = (REPO_ROOT / ".github/workflows" / workflow).read_text()
        assert f"python3 -m {module}" in text
        assert f"uv run python -m {module}" not in text
