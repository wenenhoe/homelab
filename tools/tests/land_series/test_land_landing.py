"""Landing kept branches as pull requests: the push, the pull request, the checks, the review and the merge."""

from __future__ import annotations

import sys

import pytest
from _series_repo import Author, Repo, git, series_file
from conftest import FakeGitHub
from land_series import __main__ as cli
from land_series.kept import KeptError, keep, leftovers
from land_series.land import LandError, land
from land_series.manifest import Layer, SeriesError, order_layers, parse_series
from land_series.replay import replay


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


def kept(repo: Repo, layers: list[Layer]) -> None:
    """What a run without --land does: replay on a scratch worktree, then leave a branch per layer."""
    keep(repo.path, replay(repo.path, layers, [], lambda layer, paths: False))


def two_layers(author: Author) -> list[Layer]:
    return layers_of(
        ("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})),
        ("0001b", "write-two", author.patch("docs: write two", {"b.txt": "two\n"})),
    )


def test_each_kept_layer_becomes_a_pull_request_merged_in_order_showing_only_its_own_commit(github: FakeGitHub, repo: Repo, author: Author) -> None:
    layers = two_layers(author)
    kept(repo, layers)
    reviews = Reviews(True, True)

    landed = land(repo.path, layers, reviews, sleep=lambda _: None)

    assert [(item.layer.id, item.merged) for item in landed] == [("0001a", True), ("0001b", True)]
    assert [pr["title"] for pr in github.state()["prs"]] == ["docs: write one", "docs: write two"]
    assert [merge["ahead"] for merge in github.state()["merges"]] == [1, 1]
    assert github.merges_on_main() == ["Merge pull request #2", "Merge pull request #1"]
    assert (github.file_on_main("a.txt"), github.file_on_main("b.txt")) == ("one", "two")
    assert github.branches() == ["main"]
    assert git(repo.path, "branch", "--list", "series/*") == ""
    assert reviews.asked == [("0001a", "https://example.test/pull/1"), ("0001b", "https://example.test/pull/2")]


def test_the_pushed_commit_is_the_kept_one_with_what_the_apply_hooks_folded_into_it(github: FakeGitHub, repo: Repo, author: Author) -> None:
    repo.install_hook("post-applypatch", "echo regenerated >> base.txt\ngit add base.txt\ngit commit --amend --no-edit --quiet --no-verify\n")
    layers = layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})))
    kept(repo, layers)
    reviewed = git(repo.path, "rev-parse", "series/write-one")
    land(repo.path, layers, Reviews(False), sleep=lambda _: None)

    assert git(github.remote, "rev-parse", "write-one") == reviewed
    assert git(github.remote, "show", "write-one:base.txt").splitlines()[-1] == "regenerated"


def test_a_declined_review_leaves_the_pull_request_and_the_kept_branches_in_place(github: FakeGitHub, repo: Repo, author: Author) -> None:
    layers = two_layers(author)
    kept(repo, layers)

    landed = land(repo.path, layers, Reviews(False), sleep=lambda _: None)

    assert [(item.layer.id, item.merged, item.url) for item in landed] == [("0001a", False, "https://example.test/pull/1")]
    assert github.merges_on_main() == []
    assert github.branches() == ["main", "write-one"]
    assert git(repo.path, "branch", "--list", "series/*").split() == ["series/write-one", "series/write-two"]
    assert len(github.calls("pr", "create")) == 1


def test_running_again_reuses_the_open_pull_request_without_pushing_it_again(github: FakeGitHub, repo: Repo, author: Author) -> None:
    layers = layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})))
    kept(repo, layers)
    land(repo.path, layers, Reviews(False), sleep=lambda _: None)
    pushed = git(github.remote, "rev-parse", "write-one")

    landed = land(repo.path, layers, Reviews(True), sleep=lambda _: None)

    assert [item.merged for item in landed] == [True]
    assert pushed == git(github.remote, "rev-parse", "main^2")
    assert len(github.calls("pr", "create")) == 1
    assert github.calls("pr", "edit") == []


def test_a_rebuilt_layer_replaces_the_remote_branch_and_updates_the_open_pull_request(github: FakeGitHub, repo: Repo, author: Author) -> None:
    first = layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})))
    kept(repo, first)
    land(repo.path, first, Reviews(False), sleep=lambda _: None)
    replacement = layers_of(("0001a", "write-one", Author(repo, author.path.parent / "second").patch("docs: write one, revised", {"a.txt": "uno\n"})))
    kept(repo, replacement)

    land(repo.path, replacement, Reviews(True), sleep=lambda _: None)

    assert len(github.calls("pr", "create")) == 1
    assert github.calls("pr", "edit")[0][3:5] == ["--title", "docs: write one, revised"]
    assert github.file_on_main("a.txt") == "uno"


def test_a_layer_already_in_the_base_gets_no_branch_and_no_pull_request(github: FakeGitHub, repo: Repo, author: Author) -> None:
    first = author.patch("docs: write one", {"a.txt": "one\n"})
    second = author.patch("docs: write two", {"b.txt": "two\n"})
    git(repo.path, "am", "--quiet", stdin=first)
    git(repo.path, "push", "-q", "origin", "main")
    layers = layers_of(("0001a", "write-one", first), ("0001b", "write-two", second))
    kept(repo, layers)

    landed = land(repo.path, layers, Reviews(True), sleep=lambda _: None)

    assert git(repo.path, "branch", "--list", "series/*") == ""
    assert [item.layer.id for item in landed] == ["0001b"]
    assert [pr["head"] for pr in github.state()["prs"]] == ["write-two"]


def test_checks_that_fail_stop_before_the_review_and_name_the_pull_request(
    github: FakeGitHub, repo: Repo, author: Author, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_GH_CHECKS", "fail")
    layers = layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})))
    kept(repo, layers)
    reviews = Reviews(True)

    with pytest.raises(LandError, match=r"required checks on https://example.test/pull/1 did not pass:\nbuild {2}fail") as raised:
        land(repo.path, layers, reviews, sleep=lambda _: None)

    assert reviews.asked == []
    assert raised.value.landed == []
    assert github.merges_on_main() == []


def test_checks_that_have_not_started_are_waited_for(github: FakeGitHub, repo: Repo, author: Author, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_GH_CHECKS", "late")
    layers = layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})))
    kept(repo, layers)
    waits: list[float] = []

    landed = land(repo.path, layers, Reviews(True), sleep=waits.append)

    assert [item.merged for item in landed] == [True]
    assert waits == [10]


def test_a_failure_after_a_merge_reports_what_already_landed(github: FakeGitHub, repo: Repo, author: Author, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_GH_CHECKS", "fail-second")
    layers = two_layers(author)
    kept(repo, layers)

    with pytest.raises(LandError, match="did not pass") as raised:
        land(repo.path, layers, Reviews(True), sleep=lambda _: None)

    assert [(item.layer.id, item.merged) for item in raised.value.landed] == [("0001a", True)]
    assert git(repo.path, "branch", "--list", "series/*").split() == ["series/write-two"]


@pytest.mark.usefixtures("github")
def test_keeping_leaves_a_chain_of_branches_each_on_the_one_before(repo: Repo, author: Author) -> None:
    layers = two_layers(author)

    kept(repo, layers)

    assert git(repo.path, "rev-parse", "series/write-two^") == git(repo.path, "rev-parse", "series/write-one")
    assert git(repo.path, "rev-parse", "series/write-one^") == git(repo.path, "rev-parse", "main")


@pytest.mark.usefixtures("github")
def test_keeping_again_replaces_the_branches_the_tool_left(repo: Repo, author: Author) -> None:
    layers = two_layers(author)
    kept(repo, layers)

    kept(repo, layers)

    assert git(repo.path, "branch", "--list", "series/*").split() == ["series/write-one", "series/write-two"]


@pytest.mark.usefixtures("github")
def test_keeping_refuses_a_branch_the_tool_did_not_leave_and_changes_nothing(repo: Repo, author: Author) -> None:
    layers = two_layers(author)
    git(repo.path, "branch", "series/write-two", "main")

    with pytest.raises(KeptError, match="series/write-two exists and is not as this tool left it"):
        kept(repo, layers)

    assert git(repo.path, "branch", "--list", "series/write-one") == ""
    assert git(repo.path, "rev-parse", "series/write-two") == git(repo.path, "rev-parse", "main")


def edit_branch(repo: Repo, branch: str) -> None:
    """Add a commit to the branch, as a fix made in a git client would."""
    tip = git(repo.path, "rev-parse", branch)
    edited = git(repo.path, "commit-tree", f"{tip}^{{tree}}", "-p", tip, "-m", "edit")
    git(repo.path, "branch", "--force", branch, edited)


def test_an_edited_branch_is_neither_replaced_nor_landed(github: FakeGitHub, repo: Repo, author: Author) -> None:
    layers = layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})))
    kept(repo, layers)
    edit_branch(repo, "series/write-one")

    with pytest.raises(KeptError, match="not as this tool left it"):
        kept(repo, layers)
    with pytest.raises(LandError, match="series/write-one has changed since the tool built it"):
        land(repo.path, layers, Reviews(True), sleep=lambda _: None)

    assert github.branches() == ["main"]


def test_landing_without_a_kept_branch_says_to_build_it_first(github: FakeGitHub, repo: Repo, author: Author) -> None:
    layers = layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})))

    with pytest.raises(LandError, match="layer 0001a has no series/write-one; run without --land first"):
        land(repo.path, layers, Reviews(True), sleep=lambda _: None)

    assert github.branches() == ["main"]


def test_a_branch_built_from_another_patch_is_not_landed(github: FakeGitHub, repo: Repo, author: Author) -> None:
    kept(repo, layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"}))))
    other = Author(repo, author.path.parent / "other").patch("docs: write one", {"a.txt": "uno\n"})

    with pytest.raises(LandError, match="built from a different patch than layer 0001a now has"):
        land(repo.path, layers_of(("0001a", "write-one", other)), Reviews(True), sleep=lambda _: None)

    assert github.branches() == ["main"]


def test_a_moved_base_stops_the_landing_before_anything_is_pushed(github: FakeGitHub, repo: Repo, author: Author) -> None:
    layers = layers_of(("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"})))
    kept(repo, layers)
    (repo.path / "elsewhere.txt").write_text("someone else's change\n")
    git(repo.path, "add", "-A")
    git(repo.path, "commit", "-q", "-m", "docs: elsewhere")
    git(repo.path, "push", "-q", "origin", "main")

    with pytest.raises(LandError, match="origin/main has changed since layer 0001a was built; run without --land to rebuild"):
        land(repo.path, layers, Reviews(True), sleep=lambda _: None)

    assert github.branches() == ["main"]
    assert not github.state_file.exists()


def test_a_protected_branch_cannot_be_a_layer_branch() -> None:
    with pytest.raises(SeriesError, match="'main' is a protected branch"):
        parse_series(b"0001a main\n\nFrom 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\n")


def run(series, repo: Repo, *flags: str) -> int:
    return cli.main([str(series), "--repo", str(repo.path), "--check", f"{sys.executable} -c pass", *flags])


def test_the_command_line_keeps_then_lands_a_series_and_prints_each_pull_request(
    github: FakeGitHub, repo: Repo, author: Author, tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = tmp_path / "series.txt"
    series.write_bytes(series_file([("0001a write-one", author.patch("docs: write one", {"a.txt": "one\n"}))]))

    assert run(series, repo) == 0
    assert github.branches() == ["main"]
    capsys.readouterr()
    assert run(series, repo, "--land", "--yes") == 0

    assert capsys.readouterr().out.splitlines() == ["0001a  merged  https://example.test/pull/1"]
    assert github.file_on_main("a.txt") == "one"


def test_with_no_terminal_the_command_line_stops_before_the_merge_and_says_where(
    github: FakeGitHub, repo: Repo, author: Author, tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = tmp_path / "series.txt"
    series.write_bytes(series_file([("0001a write-one", author.patch("docs: write one", {"a.txt": "one\n"}))]))
    run(series, repo)
    capsys.readouterr()

    status = run(series, repo, "--land")

    captured = capsys.readouterr()
    assert status == 1
    assert "0001a  left open  https://example.test/pull/1" in captured.out
    assert "stopped before merging layer 0001a" in captured.err
    assert github.merges_on_main() == []


def test_a_series_that_fails_the_replay_leaves_nothing_to_land(
    github: FakeGitHub, repo: Repo, author: Author, tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = tmp_path / "series.txt"
    series.write_bytes(series_file([("0001a write-one", author.patch("docs: write one", {"a.txt": "one\n"}))]))

    failed = cli.main([str(series), "--repo", str(repo.path), "--check", f"{sys.executable} -c 'raise SystemExit(1)'"])
    landed = run(series, repo, "--land", "--yes")

    assert (failed, landed) == (1, 1)
    assert "has no series/write-one" in capsys.readouterr().err
    assert github.branches() == ["main"]
    assert not github.state_file.exists()


def keep_series(repo: Repo, tmp_path, patches: list[tuple[str, str, bytes]], name: str) -> list[Layer]:
    series = tmp_path / name
    series.write_bytes(series_file([(f"{layer_id} {slug}", patch) for layer_id, slug, patch in patches]))
    assert run(series, repo) == 0
    return layers_of(*patches)


@pytest.mark.usefixtures("github")
def test_a_branch_for_a_layer_no_longer_in_the_series_is_reported_once(repo: Repo, author: Author, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    first = author.patch("docs: write one", {"a.txt": "one\n"})
    keep_series(repo, tmp_path, [("0001a", "write-one", first)], "first.txt")
    second = Author(repo, author.path.parent / "second").patch("docs: write other", {"b.txt": "other\n"})
    capsys.readouterr()

    keep_series(repo, tmp_path, [("0001a", "write-other", second)], "second.txt")

    assert "Left from an earlier run, not in this series: series/write-one" in capsys.readouterr().out
    assert leftovers(repo.path, layers_of(("0001a", "write-other", second))) == ["series/write-one"]


@pytest.mark.usefixtures("github")
def test_a_leftover_branch_deleted_by_hand_is_not_reported_again(repo: Repo, author: Author, tmp_path) -> None:
    first = author.patch("docs: write one", {"a.txt": "one\n"})
    keep_series(repo, tmp_path, [("0001a", "write-one", first)], "first.txt")
    git(repo.path, "branch", "-D", "series/write-one")

    assert leftovers(repo.path, []) == []
    assert leftovers(repo.path, []) == []


@pytest.mark.usefixtures("github")
def test_the_branch_of_a_layer_already_landed_is_reported(repo: Repo, author: Author, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    first = author.patch("docs: write one", {"a.txt": "one\n"})
    second = author.patch("docs: write two", {"b.txt": "two\n"})
    keep_series(repo, tmp_path, [("0001a", "write-one", first)], "first.txt")
    git(repo.path, "am", "--quiet", stdin=first)
    git(repo.path, "push", "-q", "origin", "main")
    capsys.readouterr()

    keep_series(repo, tmp_path, [("0001a", "write-one", first), ("0001b", "write-two", second)], "both.txt")

    assert "Left from an earlier run, not in this series: series/write-one" in capsys.readouterr().out


@pytest.mark.usefixtures("github")
def test_a_series_with_nothing_left_over_says_nothing_about_it(repo: Repo, author: Author, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    keep_series(repo, tmp_path, [("0001a", "write-one", author.patch("docs: write one", {"a.txt": "one\n"}))], "first.txt")

    assert "Left from an earlier run" not in capsys.readouterr().out
