"""Landing layers as pull requests: branches, the pull request, the checks, the review and the merge."""

from __future__ import annotations

import sys

import pytest
from _series_repo import Author, git, series_file
from conftest import FakeGitHub
from land_series import __main__ as cli
from land_series.land import LandError, land
from land_series.manifest import Layer, SeriesError, order_layers, parse_series


class Reviews:
    """Answers the review prompt from a list of replies, then refuses, and remembers what it was asked."""

    def __init__(self, *answers: bool) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, str]] = []

    def __call__(self, layer: Layer, url: str) -> bool:
        self.asked.append((layer.id, url))
        return self.answers.pop(0) if self.answers else False


def layers_of(*layers: tuple[str, str, bytes]) -> list[Layer]:
    return order_layers(parse_series(series_file([(f"{layer_id} {slug}", patch) for layer_id, slug, patch in layers])))


def test_each_layer_becomes_a_pull_request_merged_in_order_from_a_branch_with_only_its_own_commit(github: FakeGitHub, repo, author: Author) -> None:
    layers = layers_of(
        ("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})),
        ("0001b", "write-two", author.patch("docs: write two", {"b.txt": "two\n"})),
    )
    reviews = Reviews(True, True)

    landed = land(repo.path, layers, reviews, sleep=lambda _: None)

    assert [(item.layer.id, item.merged) for item in landed] == [("0001a", True), ("0001b", True)]
    assert [pr["title"] for pr in github.state()["prs"]] == ["docs: write one", "docs: write two"]
    assert [merge["ahead"] for merge in github.state()["merges"]] == [1, 1]
    assert github.merges_on_main() == ["Merge pull request #2", "Merge pull request #1"]
    assert (github.file_on_main("a.txt"), github.file_on_main("b.txt")) == ("one", "two")
    assert github.branches() == ["main"]
    assert reviews.asked == [("0001a", "https://example.test/pull/1"), ("0001b", "https://example.test/pull/2")]


def test_a_declined_review_leaves_the_pull_request_open_and_the_later_layers_untouched(github: FakeGitHub, repo, author: Author) -> None:
    layers = layers_of(
        ("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})),
        ("0001b", "write-two", author.patch("docs: write two", {"b.txt": "two\n"})),
    )

    landed = land(repo.path, layers, Reviews(False), sleep=lambda _: None)

    assert [(item.layer.id, item.merged, item.url) for item in landed] == [("0001a", False, "https://example.test/pull/1")]
    assert github.merges_on_main() == []
    assert github.branches() == ["main", "write-one"]
    assert len(github.calls("pr", "create")) == 1


def test_running_again_reuses_the_open_pull_request_without_pushing_it_again(github: FakeGitHub, repo, author: Author) -> None:
    layers = layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})))
    land(repo.path, layers, Reviews(False), sleep=lambda _: None)
    pushed = git(github.remote, "rev-parse", "write-one")

    landed = land(repo.path, layers, Reviews(True), sleep=lambda _: None)

    assert [item.merged for item in landed] == [True]
    assert len(github.calls("pr", "create")) == 1
    assert github.calls("pr", "edit") == []
    assert git(github.remote, "rev-parse", "main^2") == pushed


def test_a_changed_patch_replaces_the_branch_and_updates_the_open_pull_request(github: FakeGitHub, repo, author: Author) -> None:
    first = layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})))
    land(repo.path, first, Reviews(False), sleep=lambda _: None)
    revised = Author(repo, author.path.parent / "second")
    replacement = layers_of(("0001a", "write-one", revised.patch("docs: write one, revised", {"a.txt": "uno\n"})))

    land(repo.path, replacement, Reviews(True), sleep=lambda _: None)

    assert len(github.calls("pr", "create")) == 1
    assert github.calls("pr", "edit")[0][3:5] == ["--title", "docs: write one, revised"]
    assert github.file_on_main("a.txt") == "uno"


def test_a_layer_already_in_the_base_gets_no_pull_request(github: FakeGitHub, repo, author: Author) -> None:
    first = author.patch("docs: write one", {"a.txt": "one\n"})
    second = author.patch("docs: write two", {"b.txt": "two\n"})
    git(repo.path, "am", "--quiet", stdin=first)
    git(repo.path, "push", "-q", "origin", "main")

    landed = land(repo.path, layers_of(("0001a", "write-one", first), ("0001b", "write-two", second)), Reviews(True), sleep=lambda _: None)

    assert [item.layer.id for item in landed] == ["0001b"]
    assert [pr["head"] for pr in github.state()["prs"]] == ["write-two"]


def test_checks_that_fail_stop_before_the_review_and_name_the_pull_request(github: FakeGitHub, repo, author: Author, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_GH_CHECKS", "fail")
    layers = layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})))
    reviews = Reviews(True)

    with pytest.raises(LandError, match=r"required checks on https://example.test/pull/1 did not pass:\nbuild {2}fail") as raised:
        land(repo.path, layers, reviews, sleep=lambda _: None)

    assert reviews.asked == []
    assert raised.value.landed == []
    assert github.merges_on_main() == []


def test_checks_that_have_not_started_are_waited_for(github: FakeGitHub, repo, author: Author, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_GH_CHECKS", "late")
    layers = layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})))
    waits: list[float] = []

    landed = land(repo.path, layers, Reviews(True), sleep=waits.append)

    assert [item.merged for item in landed] == [True]
    assert waits == [10]


def test_a_failure_after_a_merge_reports_what_already_landed(github: FakeGitHub, repo, author: Author) -> None:
    first = author.patch("docs: write one", {"a.txt": "one\n"})
    broken = author.patch("docs: edit a missing file", {"a.txt": "two\n"})
    layers = layers_of(("0001a", "write-one", first), ("0001b", "write-two", broken.replace(b"-one", b"-zzz")))

    with pytest.raises(LandError, match="layer 0001b does not apply") as raised:
        land(repo.path, layers, Reviews(True), sleep=lambda _: None)

    assert [(item.layer.id, item.merged) for item in raised.value.landed] == [("0001a", True)]


def test_a_protected_branch_cannot_be_a_layer_branch() -> None:
    with pytest.raises(SeriesError, match="'main' is a protected branch"):
        parse_series(b"0001a main\n\nFrom 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\n")


def test_the_command_line_lands_a_series_and_prints_each_pull_request(
    github: FakeGitHub, repo, author: Author, tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = tmp_path / "series.txt"
    series.write_bytes(series_file([("0001a write-one", author.patch("docs: write one", {"a.txt": "one\n"}))]))

    status = cli.main([str(series), "--repo", str(repo.path), "--check", f"{sys.executable} -c pass", "--land", "--yes"])

    assert status == 0
    assert capsys.readouterr().out.splitlines() == ["0001a  replayed  docs: write one", "0001a  merged  https://example.test/pull/1"]
    assert github.file_on_main("a.txt") == "one"


def test_with_no_terminal_the_command_line_stops_before_the_merge_and_says_where(
    github: FakeGitHub, repo, author: Author, tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = tmp_path / "series.txt"
    series.write_bytes(series_file([("0001a write-one", author.patch("docs: write one", {"a.txt": "one\n"}))]))

    status = cli.main([str(series), "--repo", str(repo.path), "--check", f"{sys.executable} -c pass", "--land"])

    captured = capsys.readouterr()
    assert status == 1
    assert "0001a  left open  https://example.test/pull/1" in captured.out
    assert "stopped before merging layer 0001a" in captured.err
    assert github.merges_on_main() == []


def test_a_series_that_fails_the_replay_is_never_pushed(github: FakeGitHub, repo, author: Author, tmp_path) -> None:
    series = tmp_path / "series.txt"
    series.write_bytes(series_file([("0001a write-one", author.patch("docs: write one", {"a.txt": "one\n"}))]))

    status = cli.main([str(series), "--repo", str(repo.path), "--check", f"{sys.executable} -c 'raise SystemExit(1)'", "--land", "--yes"])

    assert status == 1
    assert github.branches() == ["main"]
    assert not github.state_file.exists()
