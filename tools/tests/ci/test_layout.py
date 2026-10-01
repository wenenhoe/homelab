"""Where code lives (ADR 0064): the repo's layout rules, as tests.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS = REPO_ROOT / "tools"
GITHUB = REPO_ROOT / ".github"
# Where a workflow, composite action or pre-commit hook may name a module to run.
CALLERS = [*sorted((GITHUB / "workflows").glob("*.yml")), *sorted((GITHUB / "actions").glob("*/action.yml")), REPO_ROOT / ".config/.pre-commit-config.yaml"]
MODULE_RUN = re.compile(r"python3? -m ((?:ci|doc_scripts)(?:\.\w+)+)")
MODULE_RUNS = [(caller, module) for caller in CALLERS for module in MODULE_RUN.findall(caller.read_text())]
DISTINCT_MODULE_RUNS = list(dict.fromkeys(MODULE_RUNS))
TEST_FILES = [path for path in sorted((TOOLS / "tests").rglob("*.py")) if path.name != Path(__file__).name]
PACKAGES = sorted(init.parent.name for init in TOOLS.glob("*/__init__.py"))


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


class TestLayout:
    def test_github_scripts_holds_no_python(self):
        assert sorted(p.name for p in (GITHUB / "scripts").rglob("*.py")) == []

    @pytest.mark.parametrize("path", TEST_FILES, ids=_relative)
    def test_no_test_reaches_into_dot_github_for_code(self, path):
        assert ".github/scripts" not in path.read_text().replace("tools/doc_scripts", ""), "imports or runs code from .github/scripts"

    @pytest.mark.parametrize("caller", CALLERS, ids=_relative)
    def test_no_caller_runs_a_python_file_from_dot_github(self, caller):
        assert not re.search(r"python3?\s+\.github/scripts/\S+\.py", caller.read_text())

    @pytest.mark.parametrize(("caller", "module"), DISTINCT_MODULE_RUNS, ids=lambda value: _relative(value) if isinstance(value, Path) else value)
    def test_every_module_a_caller_runs_exists(self, caller, module):
        assert (TOOLS / (module.replace(".", "/") + ".py")).is_file(), f"tools/{module.replace('.', '/')}.py"

    def test_enough_module_runs_are_found_for_the_existence_check_to_mean_something(self):
        assert len(MODULE_RUNS) > 20

    @pytest.mark.parametrize("package", PACKAGES)
    def test_every_package_under_tools_triggers_the_unit_tests(self, package):
        filters = yaml.safe_load((GITHUB / "detect-changes-filters.yml").read_text())["python_unit_tests"]
        assert f"tools/{package}/**" in filters

    @pytest.mark.parametrize("package", PACKAGES)
    def test_package_names_do_not_shadow_the_standard_library(self, package):
        assert package not in sys.stdlib_module_names
