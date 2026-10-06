"""Unit tests for filter_plugins/cd_agent_chain.py.

Run via `uv run pytest ansible/tests/ -v`. The filter is a pure function,
so it is imported directly rather than through an Ansible run.
"""

from __future__ import annotations

import cd_agent_chain as filter_mod
import pytest

cd_agent_chain_errors = filter_mod.cd_agent_chain_errors


def timed(name: str, *successors: str) -> dict:
    return {"name": name, "poll_interval": "5min", "command": ["/bin/true"], **({"successors": list(successors)} if successors else {})}


def chained(name: str, *successors: str) -> dict:
    return {"name": name, "command": ["/bin/true"], **({"successors": list(successors)} if successors else {})}


class TestValidChains:
    @pytest.mark.parametrize(
        "jobs",
        [
            pytest.param([timed("a")], id="a-single-job"),
            pytest.param([timed("a", "b"), chained("b")], id="a-timed-job-and-its-chain-only-successor"),
            pytest.param([timed("a", "b"), timed("b")], id="a-successor-that-also-has-its-own-timer"),
            pytest.param([timed("a", "b"), chained("b", "c"), chained("c")], id="two-hops"),
            pytest.param([timed("a", "b", "c"), chained("b", "d"), chained("c", "d"), chained("d")], id="a-diamond-is-not-a-cycle"),
            pytest.param([timed("a", "c"), timed("b", "c"), chained("c")], id="two-predecessors-of-one-successor"),
            pytest.param([{**timed("a"), "successors": []}], id="an-empty-successor-list"),
            pytest.param([{"name": "a", "on_calendar": "daily", "command": ["/bin/true"]}], id="a-calendar-job"),
        ],
    )
    def test_reports_nothing(self, jobs):
        assert cd_agent_chain_errors(jobs) == []


class TestProblems:
    def test_a_successor_that_is_not_a_job(self):
        assert cd_agent_chain_errors([timed("a", "ghost")]) == ["a names successor ghost, which is not a job"]

    def test_a_job_that_follows_itself(self):
        assert cd_agent_chain_errors([timed("a", "a")]) == ["jobs form a cycle: a -> a"]

    def test_two_jobs_that_follow_each_other(self):
        assert cd_agent_chain_errors([timed("a", "b"), timed("b", "a")]) == ["jobs form a cycle: a -> b -> a"]

    def test_a_cycle_reached_through_a_tail(self):
        errors = cd_agent_chain_errors([timed("a", "b"), chained("b", "c"), chained("c", "d"), chained("d", "b")])

        assert errors == ["jobs form a cycle: b -> c -> d -> b"]

    def test_each_cycle_is_reported_once(self):
        errors = cd_agent_chain_errors([timed("a", "b"), timed("b", "a"), timed("c", "d"), timed("d", "c")])

        assert errors == ["jobs form a cycle: a -> b -> a", "jobs form a cycle: c -> d -> c"]

    def test_a_job_with_no_timer_and_no_predecessor(self):
        assert cd_agent_chain_errors([timed("a"), chained("orphan")]) == ["orphan has no timer and no predecessor, so nothing ever starts it"]

    def test_a_job_whose_only_predecessor_is_itself_is_a_cycle_and_never_started_by_another(self):
        errors = cd_agent_chain_errors([timed("a"), chained("loop", "loop")])

        assert errors == ["jobs form a cycle: loop -> loop"]

    @pytest.mark.parametrize("links", ["b", ("b",), {"b": 1}, [1], [["b"]], None])
    def test_successors_that_are_not_a_list_of_names(self, links):
        jobs = [{**timed("a"), "successors": links}, chained("b")]

        errors = cd_agent_chain_errors(jobs)

        assert "the successors of a must be a list of job names" in errors

    def test_every_problem_is_reported_together(self):
        errors = cd_agent_chain_errors([timed("a", "ghost"), chained("orphan")])

        assert errors == ["a names successor ghost, which is not a job", "orphan has no timer and no predecessor, so nothing ever starts it"]


def test_the_filter_is_registered_under_its_own_name():
    assert filter_mod.FilterModule().filters() == {"cd_agent_chain_errors": cd_agent_chain_errors}
