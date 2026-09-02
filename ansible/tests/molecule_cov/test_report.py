"""Unit tests for molecule_cov.report.

Covers the small pure formatting helpers directly, print_summary/
print_role_detail by capturing stdout, and the two threshold-checking
functions (failing_roles_under, missing_and_failing_against_thresholds) -
these used to be inline in report.py's old main(), untested; splitting
them out for the reorg made them directly testable without any file I/O.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import sys
from pathlib import Path

MOLECULE_COVERAGE_DIR = Path(__file__).resolve().parent.parent.parent / "molecule-coverage"
sys.path.insert(0, str(MOLECULE_COVERAGE_DIR))

from molecule_cov import report  # noqa: E402


def _report(role: str, coverage_pct: float | None, **summary_overrides) -> dict:
    summary = {
        "total": 4,
        "covered": 3,
        "skipped_only": 1,
        "never_observed": 0,
        "coverage_pct": coverage_pct,
        **summary_overrides,
    }
    return {"role": role, "scenarios": ["default"], "tasks": [], "summary": summary}


# --- small formatting helpers -------------------------------------------------


def test_loop_summary_none_when_task_has_no_loop():
    assert report._loop_summary(None) == "-"


def test_loop_summary_flags_a_partial_gap_with_examples():
    lc = {
        "items_observed_count": 1,
        "items_skipped_only_count": 1,
        "items_skipped_only": ['"b"'],
        "items_skipped_only_truncated": False,
        "observed_empty_loop": False,
    }
    assert report._loop_summary(lc) == '1 ok, 1 never ran ("b")'


def test_loop_summary_empty_loop_distinct_from_no_items_observed():
    empty = {
        "items_observed_count": 0,
        "items_skipped_only_count": 0,
        "items_skipped_only": [],
        "items_skipped_only_truncated": False,
        "observed_empty_loop": True,
    }
    never_reached = dict(empty, observed_empty_loop=False)
    assert report._loop_summary(empty) == "empty loop"
    assert report._loop_summary(never_reached) == "no items observed"


def test_branch_summary_maps_every_status():
    assert report._branch_summary(None) == "-"
    assert report._branch_summary({"branch_status": "both_branches"}) == "both ok"
    assert report._branch_summary({"branch_status": "true_only"}) == "never negated"
    assert report._branch_summary({"branch_status": "false_only"}) == "never satisfied"
    assert report._branch_summary({"branch_status": "never_observed"}) == "no data"


def test_has_untested_false_branch_only_true_for_true_only():
    assert report._has_untested_false_branch({"branch_coverage": {"branch_status": "true_only"}}) is True
    assert report._has_untested_false_branch({"branch_coverage": {"branch_status": "both_branches"}}) is False
    assert report._has_untested_false_branch({}) is False


def test_fmt_pct_handles_none_as_no_data():
    assert report._fmt_pct(None) == "n/a"
    # 5.1f width-padding is intentional (column alignment in print_summary/
    # print_role_detail) - not a bug to "fix" in this assertion.
    assert report._fmt_pct(80.0) == " 80.0%"


def test_discover_roles_finds_only_dirs_with_an_inventory_file(tmp_path):
    (tmp_path / "caddy").mkdir()
    (tmp_path / "caddy" / "_inventory.json").write_text("[]")
    (tmp_path / "no_inventory_yet").mkdir()
    found = report.discover_roles(tmp_path)
    assert found == [tmp_path / "caddy"]


def test_discover_roles_missing_dir_returns_empty_list(tmp_path):
    assert report.discover_roles(tmp_path / "does_not_exist") == []


# --- printing (stdout capture) -------------------------------------------------


def test_print_summary_includes_a_total_row(capsys):
    report.print_summary([_report("caddy", 100.0), _report("apt", 75.0, total=4, covered=3)])
    out = capsys.readouterr().out
    assert "TOTAL" in out
    assert "caddy" in out
    assert "apt" in out


# --- threshold checks (pure, no file I/O) --------------------------------------


def test_failing_roles_under_a_single_global_floor():
    reports = [_report("caddy", 100.0), _report("apt", 60.0)]
    assert report.failing_roles_under(reports, 80.0) == ["apt"]


def test_failing_roles_under_ignores_roles_with_no_tasks_at_all():
    reports = [_report("empty_role", None)]
    assert report.failing_roles_under(reports, 80.0) == []


def test_missing_and_failing_against_thresholds():
    reports = [_report("caddy", 100.0), _report("apt", 60.0), _report("new_role", 50.0)]
    thresholds = {"caddy": 100.0, "apt": 75.0}  # new_role deliberately has no entry
    missing, failing = report.missing_and_failing_against_thresholds(reports, thresholds)
    assert missing == ["new_role"]
    assert failing == ["apt"]


def test_a_role_missing_from_thresholds_is_not_also_double_counted_as_failing():
    reports = [_report("new_role", 0.0)]  # would obviously "fail" any real floor
    missing, failing = report.missing_and_failing_against_thresholds(reports, {})
    assert missing == ["new_role"]
    assert failing == []
