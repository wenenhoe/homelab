"""Tests for ci.spike.molecule_phases.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
from ci.spike import molecule_phases as mp

RECAP_HEAD = [
    "TASKS RECAP ********************************************************************",
    "Friday 09 October 2026  05:27:39 +0000 (0:00:00.420)       0:00:02.453 ********",
    "===============================================================================",
]


def trace(*events, start=1000.0):
    """Lines of a trace from (seconds after the first line, text) pairs."""
    return [(start + at, text) for at, text in events]


def executing(at, action, scenario="default"):
    return (at, f"INFO     [{scenario} > {action}] Executing")


def executed(at, action, scenario="default", level="INFO    "):
    return (at, f"{level} [{scenario} > {action}] Executed: Successful")


class TestPhases:
    def test_a_phase_lasts_from_executing_to_executed(self):
        lines = trace(
            (0, "INFO     [default > discovery] scenario test matrix"),
            executing(2, "prepare"),
            executed(5, "prepare"),
            executing(5, "converge"),
            executed(15, "converge"),
        )
        scenario = mp.parse_scenario("x", "default", lines)
        assert scenario.phases == {"prepare": 3, "converge": 10}
        assert scenario.total == 15

    def test_the_executed_line_counts_whatever_its_log_level(self):
        lines = trace(executing(0, "verify"), executed(4, "verify", level="WARNING "))
        assert mp.parse_scenario("x", "default", lines).phases == {"verify": 4}

    def test_time_outside_every_phase_is_reported_apart(self):
        lines = trace((0, "startup"), executing(10, "converge"), executed(40, "converge"), (50, "summary"))
        scenario = mp.parse_scenario("x", "default", lines)
        assert (scenario.total, scenario.other) == (50, 20)

    def test_a_destroy_after_create_began_is_the_final_teardown(self):
        lines = trace(
            executing(0, "destroy"), executed(1, "destroy"), executing(1, "create"), executed(30, "create"), executing(30, "destroy"), executed(35, "destroy")
        )
        assert mp.parse_scenario("x", "default", lines).phases == {"destroy": 1, "create": 29, mp.FINAL_DESTROY: 5}

    def test_a_phase_the_run_died_in_ends_at_the_last_line(self):
        lines = trace(executing(0, "converge"), (12, "fatal: [instance]: FAILED!"))
        assert mp.parse_scenario("x", "default", lines).phases == {"converge": 12}

    def test_colour_codes_do_not_hide_a_marker(self, root):
        path = root / "x" / "default.log"
        path.parent.mkdir()
        path.write_text("1000.0\t\x1b[32mINFO    \x1b[0m [default > create] Executing\n1004.0\t[default > create] Executed: Successful\n")
        (scenario,) = mp.read_traces(root)
        assert scenario.phases == {"create": 4}

    def test_an_empty_trace_has_no_time(self):
        scenario = mp.parse_scenario("x", "default", [])
        assert (scenario.total, scenario.phases, scenario.tasks) == (0.0, {}, [])


class TestRecapTasks:
    def test_each_recap_line_is_a_task_of_the_phase_that_was_open(self):
        lines = trace(
            executing(0, "converge"),
            (3, "PLAY RECAP *********************************************************************"),
            *[(3, text) for text in RECAP_HEAD],
            (3, "Converge sleep ---------------------------------------------------------- 2.02s"),
            (3, "molecule_helpers : Install fuse-overlayfs ------------------------------- 31.40s"),
            executed(4, "converge"),
        )
        assert mp.parse_scenario("x", "default", lines).tasks == [
            ("converge", "Converge sleep", 2.02),
            ("converge", "molecule_helpers : Install fuse-overlayfs", 31.40),
        ]

    def test_the_recap_ends_at_the_first_line_that_is_not_a_task(self):
        lines = trace(
            executing(0, "converge"),
            *[(3, text) for text in RECAP_HEAD],
            (3, "Converge sleep ---------------------------------------------------------- 2.02s"),
            (3, "PLAY [all] *********************************************************************"),
            (3, "Not a task ---------------------------------------------------------- 9.99s"),
        )
        assert [task for _, task, _ in mp.parse_scenario("x", "default", lines).tasks] == ["Converge sleep"]

    def test_a_task_line_outside_a_recap_is_ignored(self):
        lines = trace(executing(0, "converge"), (1, "Converge sleep ---------------------------------------------------------- 2.02s"))
        assert mp.parse_scenario("x", "default", lines).tasks == []


class TestReadTraces:
    def test_the_directory_gives_the_role_and_the_file_the_scenario(self, root):
        for role, scenario in (("a", "default"), ("b", "reset")):
            (root / role).mkdir()
            (root / role / f"{scenario}.log").write_text("1000.0\tfirst\n1007.5\tlast\n")
        assert [(s.role, s.name, s.total) for s in mp.read_traces(root)] == [("a", "default", 7.5), ("b", "reset", 7.5)]

    def test_a_line_without_a_timestamp_is_skipped(self, root):
        (root / "a").mkdir()
        (root / "a" / "default.log").write_text("not a stamp\tx\n1000.0\tfirst\n\n1002.0\tlast\n")
        assert mp.read_traces(root)[0].total == 2


class TestAggregates:
    @staticmethod
    def scenarios():
        one = mp.Scenario("a", "default", total=100, phases={"create": 30, "converge": 50, mp.FINAL_DESTROY: 5})
        one.tasks = [("prepare", "molecule_helpers : Start lldap", 20.0), ("converge", "Pull image", 12.0)]
        two = mp.Scenario("b", "default", total=60, phases={"create": 10, "converge": 40})
        two.tasks = [("prepare", "molecule_helpers : Start lldap", 10.0), ("converge", "molecule_helpers : Start lldap", 5.0)]
        return [one, two]

    def test_phases_come_in_test_order_with_their_totals(self):
        assert mp.phase_rows(self.scenarios()) == [("create", 2, 40, 20, 30), ("converge", 2, 90, 45, 50), (mp.FINAL_DESTROY, 1, 5, 5, 5)]

    def test_a_task_total_sums_across_scenarios_and_its_longest_is_per_scenario(self):
        rows = mp.task_rows(self.scenarios(), lambda task: task.startswith(mp.HELPER_PREFIX))
        assert rows == [("molecule_helpers : Start lldap", 2, 35.0, 20.0)]

    def test_the_filter_picks_the_tasks_that_pull(self):
        assert [row[0] for row in mp.task_rows(self.scenarios(), lambda task: bool(mp.PULL.search(task)))] == ["Pull image"]


class TestRender:
    def test_reports_each_section_and_each_scenario(self):
        report = mp.render(TestAggregates.scenarios())
        for heading in (
            "### Time by phase, all scenarios",
            "### Cost every scenario pays",
            "### Shared helper tasks (molecule_helpers)",
            "### Tasks that pull images",
            "### Slowest single task runs",
        ):
            assert heading in report
        assert "| a/default | 1m40s |" in report
        assert "| Start lldap | 2 | 0m35s | 0m20s |" in report

    def test_the_fixed_cost_is_the_phases_every_scenario_pays_plus_the_gaps(self):
        report = mp.render(TestAggregates.scenarios())
        # create 40 + final destroy 5 + gaps (160 total - 135 in phases = 25) = 70 of 160
        assert "add up to **1m10s** (44% of scenario time)" in report

    def test_no_traces_says_so(self):
        assert "No scenario traces were uploaded." in mp.render([])


@pytest.mark.parametrize(
    ("line", "task", "seconds"),
    [
        ("Converge sleep ---------------------------------------------------------- 2.02s", "Converge sleep", "2.02"),
        ("molecule_helpers : Start lldap ------------------------------------------ 123.45s", "molecule_helpers : Start lldap", "123.45"),
    ],
    ids=["short", "role-prefixed-three-digit-seconds"],
)
def test_recap_line_pattern(line, task, seconds):
    match = mp.RECAP_TASK.match(line)
    assert (match["task"], match["seconds"]) == (task, seconds)
