"""Unit tests for openbao_utils.diff.

Run via `uv run pytest tools/tests/ -v`. Real tmp directories with
real files - this tool is pure filesystem comparison, no Vault
involved, so no mocking needed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from openbao_utils import diff


@pytest.fixture
def dirs(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    tmp = tmp_path_factory.mktemp("diff")
    dir_a = tmp / "a"
    dir_b = tmp / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    return SimpleNamespace(tmp=tmp, dir_a=dir_a, dir_b=dir_b)


def _write(d: Path, name: str, value: str) -> None:
    (d / name).write_text(value)


class TestDiff:
    def test_identical_directories_return_zero(self, dirs):
        _write(dirs.dir_a, "key1", "same-value")
        _write(dirs.dir_b, "key1", "same-value")
        rc = diff._compare(dirs.dir_a, dirs.dir_b, set())
        assert rc == 0

    def test_differing_value_returns_one(self, dirs):
        _write(dirs.dir_a, "key1", "old-value")
        _write(dirs.dir_b, "key1", "new-value")
        rc = diff._compare(dirs.dir_a, dirs.dir_b, set())
        assert rc == 1

    def test_key_only_in_a_returns_one(self, dirs):
        _write(dirs.dir_a, "orphan-key", "value")
        _write(dirs.dir_a, "shared", "x")
        _write(dirs.dir_b, "shared", "x")
        rc = diff._compare(dirs.dir_a, dirs.dir_b, set())
        assert rc == 1

    def test_key_only_in_b_returns_one(self, dirs):
        _write(dirs.dir_a, "shared", "x")
        _write(dirs.dir_b, "shared", "x")
        _write(dirs.dir_b, "new-key", "value")
        rc = diff._compare(dirs.dir_a, dirs.dir_b, set())
        assert rc == 1

    def test_ignored_key_does_not_affect_verdict_even_if_it_differs(self, dirs):
        _write(dirs.dir_a, "rotated-key", "old-value")
        _write(dirs.dir_b, "rotated-key", "new-value")
        _write(dirs.dir_a, "shared", "x")
        _write(dirs.dir_b, "shared", "x")
        rc = diff._compare(dirs.dir_a, dirs.dir_b, {"rotated-key"})
        assert rc == 0

    def test_ignored_key_only_present_in_one_side_does_not_affect_verdict(self, dirs):
        _write(dirs.dir_a, "dropped-key", "value")
        _write(dirs.dir_a, "shared", "x")
        _write(dirs.dir_b, "shared", "x")
        rc = diff._compare(dirs.dir_a, dirs.dir_b, {"dropped-key"})
        assert rc == 0

    def test_never_prints_a_secret_value(self, dirs):
        _write(dirs.dir_a, "key1", "super-secret-value-a")
        _write(dirs.dir_b, "key1", "super-secret-value-b")
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            diff._compare(dirs.dir_a, dirs.dir_b, set())

        output = buf.getvalue()
        assert "super-secret-value-a" not in output
        assert "super-secret-value-b" not in output
        assert "key1" in output

    def test_main_rejects_a_non_directory_argument(self, dirs):
        from unittest.mock import patch

        with patch.object(sys, "argv", ["diff.py", str(dirs.dir_a), str(dirs.tmp / "nope")]):
            rc = diff.main()
        assert rc == 2
