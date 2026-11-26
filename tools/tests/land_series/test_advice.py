"""The advice on asking for a review that a replay and the merge prompt print."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from _series_repo import Author, Repo, git, series_file
from land_series import __main__ as cli
from land_series.advice import advice, kept_advice, replay_advice
from land_series.kept import branch_of, keep
from land_series.manifest import Layer, group_pulls, order_layers, parse_series
from land_series.replay import replay

WORKFLOW = {".github/workflows/x.yml": "on: push\n"}
ADVICE = [
    "Worth asking for a review:",
    "  R1: automation or a tool that holds credentials or deploys: workflows, git hooks, dependencies, "
    "the deploy and credential tools (.github/workflows/x.yml)",
    "  How to ask: docs/topics/security/policy/pr-review.md",
]


def allow(stops: object) -> bool:
    """Answers the stop prompt: a series that touches `.github/` stops for confirmation."""
    return True


def layers_of(*layers: tuple[str, str, bytes]) -> list[Layer]:
    return order_layers(parse_series(series_file([(f"{layer_id} {slug}", patch) for layer_id, slug, patch in layers])))


def quiet_then_risky(author: Author) -> list[Layer]:
    return layers_of(
        ("0001a", "quiet-change", author.patch("docs: write one", {"a.txt": "one\n"})),
        ("0002a", "workflow-change", author.patch("ci: change the workflow", WORKFLOW)),
    )


def test_a_pull_request_that_trips_a_major_criterion_gets_advice_and_a_quiet_one_gets_none(repo: Repo, author: Author) -> None:
    results = replay(repo.path, quiet_then_risky(author), [], allow, base="main")

    assert replay_advice(repo.path, results) == ["Pull request 0002 (ci: change the workflow):", *ADVICE]


def test_a_layer_already_in_the_base_gets_no_advice(repo: Repo, author: Author) -> None:
    layers = quiet_then_risky(author)
    results = replay(repo.path, layers, [], allow, base="main")
    git(repo.path, "merge", "-q", "--ff-only", results[1].commit or "")
    assert replay_advice(repo.path, replay(repo.path, layers, [], allow, base="main")) == []


def test_a_pull_request_of_several_commits_is_judged_on_all_of_them(repo: Repo, author: Author) -> None:
    layers = layers_of(
        ("0001a", "tidy", author.patch("docs: write one", {"a.txt": "one\n"})),
        ("0001b", "tidy", author.patch("ci: change the workflow", WORKFLOW)),
    )
    results = replay(repo.path, layers, [], allow, base="main")
    assert replay_advice(repo.path, results) == ["Pull request 0001 (docs: write one):", *ADVICE]


def test_the_advice_for_a_kept_branch_reads_the_commits_of_that_pull_request_only(repo: Repo, author: Author) -> None:
    layers = quiet_then_risky(author)
    keep(repo.path, replay(repo.path, layers, [], allow, base="main"))
    quiet, risky = group_pulls(layers)

    assert kept_advice(repo.path, quiet, branch_of(quiet)) == []
    assert kept_advice(repo.path, risky, branch_of(risky)) == ADVICE


def test_a_diff_that_cannot_be_read_gives_no_advice(repo: Repo) -> None:
    assert advice(repo.path, "no-such-commit", 1) == []


@pytest.mark.usefixtures("github")
def test_the_command_line_prints_the_advice_after_the_replayed_layers(
    repo: Repo, author: Author, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    series = tmp_path / "series.txt"
    series.write_bytes(series_file([("0001a workflow-change", author.patch("ci: change the workflow", WORKFLOW))]))
    monkeypatch.setattr(cli, "ask", allow)

    status = cli.main([str(series), "--repo", str(repo.path), "--no-fetch", "--dry-run", "--check", f"{sys.executable} -c pass"])

    assert status == 0
    assert capsys.readouterr().out.splitlines() == ["0001a  replayed  ci: change the workflow", "Pull request 0001 (ci: change the workflow):", *ADVICE]


def test_the_merge_prompt_shows_the_advice_before_it_asks(author: Author, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    (pull,) = group_pulls(layers_of(("0001a", "one", author.patch("docs: one", {"a.txt": "one\n"}))))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "no")

    assert cli.ask_merge(pull, "https://example.test/pull/1", ADVICE) is False
    assert capsys.readouterr().out.splitlines()[-len(ADVICE) :] == ADVICE
