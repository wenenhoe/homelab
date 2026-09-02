"""Unit tests for molecule_cov.cli's argument parsing.

Covers the MOLECULE_COVERAGE_DIR env-var default specifically - both
`inventory` and `report` must fall back to it identically. Before this
fix, `report`'s default silently ignored the env var while `inventory`'s
honored it, an inherited inconsistency from the pre-reorg scripts.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import sys
from pathlib import Path

MOLECULE_COVERAGE_DIR = Path(__file__).resolve().parent.parent.parent / "molecule-coverage"
sys.path.insert(0, str(MOLECULE_COVERAGE_DIR))

from molecule_cov import cli  # noqa: E402


def test_inventory_coverage_dir_defaults_to_the_env_var(monkeypatch):
    monkeypatch.setenv("MOLECULE_COVERAGE_DIR", "/tmp/from-env")
    args = cli._build_parser().parse_args(["inventory", "some/role"])
    assert args.coverage_dir == Path("/tmp/from-env")


def test_report_coverage_dir_also_defaults_to_the_env_var(monkeypatch):
    monkeypatch.setenv("MOLECULE_COVERAGE_DIR", "/tmp/from-env")
    args = cli._build_parser().parse_args(["report"])
    assert args.coverage_dir == Path("/tmp/from-env")


def test_both_subcommands_fall_back_to_the_same_default_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("MOLECULE_COVERAGE_DIR", raising=False)
    inventory_args = cli._build_parser().parse_args(["inventory", "some/role"])
    report_args = cli._build_parser().parse_args(["report"])
    assert inventory_args.coverage_dir == report_args.coverage_dir == Path("./.molecule-coverage-data")


def test_explicit_flag_overrides_the_env_var(monkeypatch):
    monkeypatch.setenv("MOLECULE_COVERAGE_DIR", "/tmp/from-env")
    args = cli._build_parser().parse_args(["report", "--coverage-dir", "/tmp/explicit"])
    assert args.coverage_dir == Path("/tmp/explicit")
