"""Unit tests for filter_plugins/cron_period_hours.py.

Run via `uv run pytest ansible/tests/ -v`. The filter is a pure function,
so it is imported directly rather than through an Ansible run.
"""

from __future__ import annotations

import datetime

import cron_period_hours as filter_mod
import pytest

cron_period_hours = filter_mod.cron_period_hours


@pytest.mark.parametrize(
    ("cron_expr", "hours"),
    [
        ("0 2 * * *", 24),
        ("0 */6 * * *", 6),
        # Friday 02:00 to Monday 02:00 is the worst gap, not the 24h average.
        ("0 2 * * 1-5", 72),
        ("* * * * *", 1),
        ("0 3 * * 0", 168),
        # 31 days, from a fixed reference date that begins on the 1st.
        ("0 0 1 * *", 744),
    ],
)
def test_worst_case_gap_in_whole_hours(cron_expr, hours):
    assert cron_period_hours(cron_expr) == hours


def test_same_input_gives_the_same_output():
    results = {cron_period_hours("30 4 * * 1-5") for _ in range(5)}
    assert len(results) == 1


def test_reference_is_a_fixed_date_not_the_current_time():
    # A clock-anchored reference would change the monthly result with the
    # month it runs in, and Ansible's idempotence check would then fail.
    assert datetime.datetime(2024, 1, 1) == filter_mod._REFERENCE


@pytest.mark.parametrize("cron_expr", ["not a cron", "", "61 * * * *"])
def test_invalid_expression_raises(cron_expr):
    with pytest.raises(ValueError, match=r"."):
        cron_period_hours(cron_expr)


def test_filter_module_registers_the_filter_under_its_own_name():
    assert filter_mod.FilterModule().filters() == {"cron_period_hours": cron_period_hours}
