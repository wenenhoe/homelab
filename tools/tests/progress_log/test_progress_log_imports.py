"""The progress log runs on the runner's own python3 with nothing installed, so it imports only the standard library and itself."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "progress_log"
MODULES = sorted(PACKAGE.glob("*.py"), key=lambda path: path.name)


def _imported(tree: ast.AST) -> list[str]:
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            modules.append(node.module or "")
    return modules


@pytest.mark.parametrize("module", MODULES, ids=lambda path: path.name)
def test_imports_the_standard_library_or_itself_only(module, subtests):
    for name in _imported(ast.parse(module.read_text())):
        with subtests.test(module=name):
            assert name.split(".")[0] in sys.stdlib_module_names or name.split(".")[0] == "progress_log", f"{module.name} imports {name}"


def test_the_package_has_modules_to_check():
    assert len(MODULES) >= 5
