"""Tests for ci_scope.effective_changes against a real git history.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ci_scope import effective_changes as ec

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
PY = "ansible/tests/test_x.py"
PYPROJECT = '[project]\nname = "x"\ndependencies = ["a>=1"]\n\n[tool.ruff]\nline-length = 160\n'


class EffectiveChangesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.git("init", "-q")
        self.write(PY, "def test():\n    assert 1\n")
        self.write("tools/tests/test_y.py", "def test():\n    assert 2\n")
        self.write("pyproject.toml", PYPROJECT)
        self.write("uv.lock", 'version = 1\n[[package]]\nname = "a"\n')
        self.base = self.commit("base")

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, env={**os.environ, **GIT_ENV}, capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def evaluate(self, **files: list[str]) -> dict[str, bool]:
        head = self.commit("change")
        env = {f"{name.upper()}_FILES": json.dumps(paths) for name, paths in files.items()}
        with patch.dict(os.environ, env):
            return ec.evaluate(self.root, self.base, head, list(files))

    def test_comment_only_change_leaves_the_filter_false(self):
        self.write(PY, "# note\ndef test():\n    assert 1\n")
        self.assertEqual(self.evaluate(python_unit_tests=[PY]), {"python_unit_tests": False})

    def test_real_change_makes_the_filter_true(self):
        self.write(PY, "def test():\n    assert 3\n")
        self.assertEqual(self.evaluate(python_unit_tests=[PY]), {"python_unit_tests": True})

    def test_one_real_change_among_no_ops_is_enough(self):
        self.write(PY, "# note\ndef test():\n    assert 1\n")
        self.write("tools/tests/test_y.py", "def test():\n    assert 9\n")
        self.assertTrue(self.evaluate(python_unit_tests=[PY, "tools/tests/test_y.py"])["python_unit_tests"])

    def test_no_matched_files_is_false(self):
        self.assertEqual(self.evaluate(uv_lock=[]), {"uv_lock": False})

    def test_ruff_only_pyproject_change_leaves_lock_and_deploy_filters_false(self):
        self.write("pyproject.toml", PYPROJECT.replace("160", "100"))
        result = self.evaluate(uv_lock=["pyproject.toml"], deploy_ordering=["pyproject.toml"], python_unit_tests=["pyproject.toml"])
        self.assertEqual(result, {"uv_lock": False, "deploy_ordering": False, "python_unit_tests": False})

    def test_dependency_change_makes_every_filter_true(self):
        self.write("pyproject.toml", PYPROJECT.replace("a>=1", "a>=2"))
        result = self.evaluate(uv_lock=["pyproject.toml"], deploy_ordering=["pyproject.toml"], python_unit_tests=["pyproject.toml"])
        self.assertEqual(set(result.values()), {True})

    def test_lock_change_is_real(self):
        self.write("uv.lock", 'version = 1\n[[package]]\nname = "b"\n')
        self.assertTrue(self.evaluate(uv_lock=["uv.lock"])["uv_lock"])

    def test_deleted_file_is_real(self):
        (self.root / PY).unlink()
        self.assertTrue(self.evaluate(python_unit_tests=[PY])["python_unit_tests"])

    def test_gated_filters_never_include_the_ones_that_read_comments(self):
        for name in ("ansible_lint", "trivy_ansible", "any_compose"):
            with self.subTest(name=name), patch.dict(os.environ, {f"{name.upper()}_FILES": "[]"}), self.assertRaisesRegex(ec.FilterError, "can't be gated"):
                ec.evaluate(self.root, self.base, self.base, [name])

    def test_missing_or_malformed_file_list_is_an_error(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("UV_LOCK_FILES", None)
            with self.assertRaisesRegex(ec.FilterError, "UV_LOCK_FILES is not set"):
                ec.files_from_env("uv_lock")
        for bad in ("not json", '{"a": 1}', "[1, 2]"):
            with self.subTest(value=bad), patch.dict(os.environ, {"UV_LOCK_FILES": bad}), self.assertRaises(ec.FilterError):
                ec.files_from_env("uv_lock")

    def test_main_writes_every_filter_to_the_output_file(self):
        self.write(PY, "# note\ndef test():\n    assert 1\n")
        self.write("uv.lock", 'version = 1\n[[package]]\nname = "b"\n')
        head = self.commit("change")
        out = self.root / "out.txt"
        env = {"GITHUB_OUTPUT": str(out), "PYTHON_UNIT_TESTS_FILES": json.dumps([PY]), "UV_LOCK_FILES": json.dumps(["uv.lock"])}
        with patch.object(ec, "REPO_ROOT", self.root), patch.dict(os.environ, env):
            self.assertEqual(ec.main([self.base, head, "python_unit_tests", "uv_lock"]), 0)
        self.assertEqual(out.read_text().splitlines(), ["python_unit_tests=false", "uv_lock=true"])

    def test_main_fails_on_a_bad_filter(self):
        with patch.object(ec, "REPO_ROOT", self.root), patch.dict(os.environ, {"ANSIBLE_LINT_FILES": "[]"}):
            self.assertEqual(ec.main([self.base, self.base, "ansible_lint"]), 1)


if __name__ == "__main__":
    unittest.main()
