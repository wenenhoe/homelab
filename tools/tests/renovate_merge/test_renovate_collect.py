from pathlib import Path

import pytest
from _bodies import BREAKING_NOTES, body
from conftest import FakeGitHub
from renovate_merge import collect, flags


def test_collect_reads_updates_notes_and_level_of_each_pull_request(github: FakeGitHub, tmp_path: Path) -> None:
    number = github.add_pull(title="chore(deps): update example/tool to v2", description=body("example/tool", "1.9.9", "2.0.0", BREAKING_NOTES))

    [pull] = collect.collect(tmp_path, "maintenance")

    assert (pull.number, pull.level) == (number, flags.LEVEL_BREAKING)
    assert pull.head_sha == "0000001" + "a" * 33
    assert [(update.old, update.new, update.kind) for update in pull.updates] == [("1.9.9", "2.0.0", "major")]
    assert {flag.category for flag in pull.flags} == {"breaking", "warning", "removal"}
    assert "--compat" in pull.notes


def test_collect_returns_the_pull_requests_by_number(github: FakeGitHub, tmp_path: Path) -> None:
    for _ in range(3):
        github.add_pull()

    assert [pull.number for pull in collect.collect(tmp_path, "maintenance")] == [1, 2, 3]


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"fork": True}, id="from-a-fork"),
        pytest.param({"branch": "feature/tool"}, id="branch-not-renovates"),
        pytest.param({"login": "someone"}, id="author-not-renovate"),
        pytest.param({"base": "develop"}, id="other-base"),
    ],
)
def test_collect_skips_a_pull_request_that_is_not_renovates(github: FakeGitHub, tmp_path: Path, kwargs: dict) -> None:
    github.add_pull(**kwargs)

    assert collect.collect(tmp_path, "maintenance") == []


def test_collect_takes_a_renovate_warning_from_outside_the_release_notes(github: FakeGitHub, tmp_path: Path) -> None:
    description = body("example/tool", "1.4.2", "1.4.3", "- Fix a crash").replace("This PR contains", "> ⚠ **Warning** lookup failed\n\nThis PR contains")
    github.add_pull(description=description)

    [pull] = collect.collect(tmp_path, "maintenance")

    assert [flag.category for flag in pull.flags] == ["warning"]
    assert pull.level == flags.LEVEL_BREAKING


def test_collect_reads_a_pull_request_with_no_description(github: FakeGitHub, tmp_path: Path) -> None:
    github.add_pull(description="")

    [pull] = collect.collect(tmp_path, "maintenance")

    assert (pull.updates, pull.notes, pull.flags, pull.level) == ([], "", [], flags.LEVEL_NONE)
