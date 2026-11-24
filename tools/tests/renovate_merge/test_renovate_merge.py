import json
from pathlib import Path

import pytest
from conftest import FakeGitHub
from renovate_merge import merge as merging
from renovate_merge.merge import MergeError, Reviewed, Summary

SHA = "0000001" + "a" * 33


def summary_text(*pulls: dict, base: str = "maintenance") -> str:
    return json.dumps({"base": base, "generated": "x", "pulls": list(pulls)})


def item(number: int, level: str = "none", sha: str | None = None) -> dict:
    return {
        "number": number,
        "title": f"title {number}",
        "url": f"https://example.test/pull/{number}",
        "head_sha": sha or f"{number:07d}" + "a" * 33,
        "level": level,
    }


def summary_of(*pulls: dict) -> Summary:
    return merging.load_summary(summary_text(*pulls))


def go(repo: Path, summary: Summary, chosen: list[Reviewed], confirm: merging.Confirm = lambda _: True, dry_run: bool = False) -> list[merging.Outcome]:
    return merging.merge(repo, summary, chosen, confirm, dry_run=dry_run, sleep=lambda _: None)


class TestLoadSummary:
    def test_reads_the_branch_and_each_pull_request(self) -> None:
        summary = summary_of(item(1), item(2, "breaking"))

        assert summary.base == "maintenance"
        assert summary.pulls[2] == Reviewed(2, "title 2", "https://example.test/pull/2", "0000002" + "a" * 33, "breaking")

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("not json", id="not-json"),
            pytest.param("[]", id="a-list"),
            pytest.param('{"base": "maintenance"}', id="no-pulls"),
            pytest.param('{"base": "maintenance", "pulls": [{"number": 1}]}', id="pull-without-head"),
            pytest.param('{"base": 3, "pulls": []}', id="branch-not-a-string"),
            pytest.param(
                '{"base": "maintenance", "pulls": [{"number": "1", "title": "t", "url": "u", "head_sha": "s", "level": "none"}]}', id="number-a-string"
            ),
        ],
    )
    def test_refuses_what_the_summary_command_did_not_write(self, text: str) -> None:
        with pytest.raises(MergeError, match="not a summary written by"):
            merging.load_summary(text)

    def test_refuses_main_unless_allowed(self) -> None:
        with pytest.raises(MergeError, match="merging into main needs --allow-main"):
            merging.load_summary(summary_text(item(1), base="main"))

    def test_reads_main_when_allowed(self) -> None:
        assert merging.load_summary(summary_text(item(1), base="main"), allow_main=True).base == "main"


class TestSelect:
    def test_with_no_numbers_takes_every_pull_request_at_level_none(self) -> None:
        summary = summary_of(item(3), item(1, "notable"), item(2, "breaking"), item(4))

        assert [pull.number for pull in merging.select(summary, [])] == [3, 4]

    def test_named_numbers_are_taken_whatever_their_level_in_number_order(self) -> None:
        summary = summary_of(item(1), item(2, "breaking"), item(3, "notable"))

        assert [pull.number for pull in merging.select(summary, [3, 2, 3])] == [2, 3]

    def test_a_number_not_in_the_summary_is_refused(self) -> None:
        with pytest.raises(MergeError, match=r"not in the summary: #9"):
            merging.select(summary_of(item(1)), [1, 9])


class TestMerge:
    def test_merges_a_pull_request_once_its_required_checks_passed(self, github: FakeGitHub, tmp_path: Path) -> None:
        number = github.add_pull()
        summary = summary_of(item(number))

        outcomes = go(tmp_path, summary, list(summary.pulls.values()))

        assert [(o.number, o.merged, o.reason) for o in outcomes] == [(number, True, "")]
        assert github.merged() == [number]
        merge_call = next(call for call in github.calls() if call[:2] == ["pr", "merge"])
        assert merge_call[merge_call.index("--match-head-commit") + 1] == SHA

    def test_waits_while_a_required_check_is_pending_and_then_merges(self, github: FakeGitHub, tmp_path: Path) -> None:
        number = github.add_pull(checks=[[["build", "pending"]], [["build", "pending"]], [["build", "pass"]]])
        summary = summary_of(item(number))
        pauses: list[float] = []

        outcomes = merging.merge(tmp_path, summary, list(summary.pulls.values()), lambda _: True, sleep=pauses.append)

        assert outcomes[0].merged
        assert pauses == [merging.CHECKS_INTERVAL_SECONDS] * 2

    def test_waits_for_a_required_check_that_is_not_reported_yet(self, github: FakeGitHub, tmp_path: Path) -> None:
        number = github.add_pull(checks=[[], [["build", "pass"]]])
        summary = summary_of(item(number))

        assert go(tmp_path, summary, list(summary.pulls.values()))[0].merged

    def test_leaves_a_pull_request_whose_required_check_failed_and_goes_on(self, github: FakeGitHub, tmp_path: Path) -> None:
        failing = github.add_pull(checks=[[["build", "fail"]]])
        passing = github.add_pull()
        summary = summary_of(item(failing), item(passing))

        outcomes = go(tmp_path, summary, list(summary.pulls.values()))

        assert [(o.number, o.merged) for o in outcomes] == [(failing, False), (passing, True)]
        assert outcomes[0].reason == "required checks failed: build"
        assert github.merged() == [passing]

    def test_a_check_that_is_not_required_does_not_hold_a_merge_back(self, github: FakeGitHub, tmp_path: Path) -> None:
        number = github.add_pull(checks=[[["build", "pass"], ["optional", "fail"]]])
        summary = summary_of(item(number))

        assert go(tmp_path, summary, list(summary.pulls.values()))[0].merged

    def test_gives_up_on_checks_that_never_pass(self, github: FakeGitHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(merging, "CHECKS_MAX_POLLS", 3)
        number = github.add_pull(checks=[[["build", "pending"]]])
        summary = summary_of(item(number))

        [outcome] = go(tmp_path, summary, list(summary.pulls.values()))

        assert not outcome.merged
        assert "still not passing after" in outcome.reason
        assert "build" in outcome.reason
        assert github.merged() == []

    def test_refuses_a_pull_request_whose_head_moved_since_the_summary(self, github: FakeGitHub, tmp_path: Path) -> None:
        number = github.add_pull(sha="b" * 40)
        summary = summary_of(item(number, sha="a" * 40))

        [outcome] = go(tmp_path, summary, list(summary.pulls.values()))

        assert not outcome.merged
        assert outcome.reason == "its head moved from aaaaaaa to bbbbbbb since the summary was read; run `summary` again"
        assert github.merged() == []

    def test_refuses_a_pull_request_that_is_no_longer_open(self, github: FakeGitHub, tmp_path: Path) -> None:
        number = github.add_pull()
        state = github.state()
        state["prs"][0]["state"] = "CLOSED"
        github.save(state)
        summary = summary_of(item(number))

        assert go(tmp_path, summary, list(summary.pulls.values()))[0].reason == "it is closed"

    def test_refuses_a_pull_request_retargeted_to_another_branch(self, github: FakeGitHub, tmp_path: Path) -> None:
        number = github.add_pull()
        state = github.state()
        state["prs"][0]["listed"]["baseRefName"] = "main"
        github.save(state)
        summary = summary_of(item(number))

        assert go(tmp_path, summary, list(summary.pulls.values()))[0].reason == "it now targets main, not maintenance"
        assert github.merged() == []

    def test_reports_the_reason_github_gives_when_it_refuses_the_merge(self, github: FakeGitHub, tmp_path: Path) -> None:
        number = github.add_pull()
        state = github.state()
        state["merge_error"] = "Repository rule violations found\n\nRequired status check is expected"
        github.save(state)
        summary = summary_of(item(number))

        [outcome] = go(tmp_path, summary, list(summary.pulls.values()))

        assert not outcome.merged
        assert "Repository rule violations found Required status check is expected" in outcome.reason

    def test_asks_before_changing_anything_and_merges_nothing_when_refused(self, github: FakeGitHub, tmp_path: Path) -> None:
        number = github.add_pull()
        summary = summary_of(item(number))

        with pytest.raises(MergeError, match="not confirmed; nothing was merged"):
            go(tmp_path, summary, list(summary.pulls.values()), confirm=lambda _: False)

        assert github.merged() == []
        assert not any(call[:2] == ["pr", "view"] for call in github.calls())

    def test_confirmation_is_given_the_pull_requests_that_will_be_merged(self, github: FakeGitHub, tmp_path: Path) -> None:
        github.add_pull()
        github.add_pull()
        summary = summary_of(item(1), item(2))
        asked: list[list[int]] = []

        go(tmp_path, summary, list(summary.pulls.values()), confirm=lambda chosen: asked.append([p.number for p in chosen]) or True)

        assert asked == [[1, 2]]

    def test_stops_when_gh_is_not_logged_in(self, github: FakeGitHub, tmp_path: Path) -> None:
        number = github.add_pull()
        state = github.state()
        state["logged_out"] = True
        github.save(state)
        summary = summary_of(item(number))

        with pytest.raises(MergeError, match="gh auth login"):
            go(tmp_path, summary, list(summary.pulls.values()))

        assert github.merged() == []

    def test_stops_when_the_rulesets_name_no_required_checks(self, github: FakeGitHub, tmp_path: Path) -> None:
        number = github.add_pull()
        state = github.state()
        state["required"] = []
        github.save(state)
        summary = summary_of(item(number))

        with pytest.raises(MergeError, match="no required status checks"):
            go(tmp_path, summary, list(summary.pulls.values()))

    def test_nothing_chosen_is_an_error_that_says_what_to_do(self, github: FakeGitHub, tmp_path: Path) -> None:
        with pytest.raises(MergeError, match="name the ones you have read"):
            go(tmp_path, summary_of(item(1, "breaking")), [])

    def test_a_dry_run_reports_each_pull_request_and_merges_nothing(self, github: FakeGitHub, tmp_path: Path) -> None:
        ready = github.add_pull()
        failing = github.add_pull(checks=[[["build", "fail"]]])
        running = github.add_pull(checks=[[["build", "pending"]]])
        moved = github.add_pull(sha="c" * 40)
        summary = summary_of(item(ready), item(failing), item(running), item(moved, sha="d" * 40))

        outcomes = go(tmp_path, summary, list(summary.pulls.values()), confirm=lambda _: pytest.fail("a dry run asks nothing"), dry_run=True)

        assert [(o.number, o.merged, o.reason) for o in outcomes] == [
            (ready, False, "dry run: ready to merge"),
            (failing, False, "dry run: required checks failed: build"),
            (running, False, "dry run: checks still to pass: build"),
            (moved, False, "its head moved from ddddddd to ccccccc since the summary was read; run `summary` again"),
        ]
        assert github.merged() == []
