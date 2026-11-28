"""The command against real repositories: what it writes, and what it refuses."""

from __future__ import annotations

from pathlib import Path

import pytest
from _delivery_repo import BOT, MAINTAINER, TRAILER, Workspace, commit, git, message
from deliver_series.__main__ import main
from land_series.manifest import order_layers, parse_base, parse_series

TITLE = "feat(gateway): declare the production gateway"


def deliver(workspace: Workspace, plan: Path, *extra: str) -> int:
    return main([str(plan), "--repo", str(workspace.work), "--out", str(workspace.out), "--build-only", *extra])


def series_files(workspace: Workspace) -> list[Path]:
    return sorted(workspace.out.iterdir())


def test_a_series_is_written_that_land_series_reads(workspace: Workspace, plan_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace.commit("feat(gateway): add the vm")
    workspace.commit("test(gateway): cover the vm")
    workspace.commit("docs(gateway): describe it")
    plan_file.write_text(f"gateway-vm 2 {TITLE}\ngateway-docs 1\n")

    assert deliver(workspace, plan_file) == 0

    [written] = series_files(workspace)
    assert capsys.readouterr().out.strip() == str(written)
    layers = order_layers(parse_series(written.read_bytes(), written.name))
    assert [(layer.id, layer.slug, layer.subject, layer.title) for layer in layers] == [
        ("0001a", "gateway-vm", "feat(gateway): add the vm", TITLE),
        ("0001b", "gateway-vm", "test(gateway): cover the vm", TITLE),
        ("0002a", "gateway-docs", "docs(gateway): describe it", None),
    ]
    assert parse_base(written.read_bytes()) is None


def test_numbering_follows_a_series_not_yet_merged(workspace: Workspace, plan_file: Path, tmp_path: Path) -> None:
    earlier = tmp_path / "earlier.series"
    workspace.commit("feat(gateway): add the vm")
    plan_file.write_text("first-try 1\n")
    assert deliver(workspace, plan_file) == 0
    [first] = series_files(workspace)
    first.rename(earlier)
    git(workspace.work, "reset", "-q", "--hard", "origin/main")
    workspace.commit("feat(gateway): add the router")
    plan_file.write_text("second-try 1\n")

    assert deliver(workspace, plan_file, "--after", str(earlier)) == 0

    [second] = series_files(workspace)
    assert [layer.id for layer in parse_series(second.read_bytes())] == ["0002a"]


def test_a_series_for_another_branch_names_it(workspace: Workspace, plan_file: Path) -> None:
    git(workspace.upstream, "branch", "develop")
    git(workspace.work, "fetch", "-q", "origin")
    git(workspace.work, "reset", "-q", "--hard", "origin/develop")
    workspace.commit("feat(gateway): add the vm")
    plan_file.write_text("gateway-vm 1\n")

    assert deliver(workspace, plan_file, "--base", "develop") == 0

    [written] = series_files(workspace)
    assert parse_base(written.read_bytes()) == "develop"


def refused(workspace: Workspace, plan: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> str:
    """Run the command, expect it to refuse, and return what it said; nothing may have been written."""
    capsys.readouterr()
    assert deliver(workspace, plan, *extra) == 1
    assert series_files(workspace) == []
    return capsys.readouterr().err


@pytest.mark.parametrize("value", [None, "false", "True", ""], ids=["unset", "false", "capitalised", "empty"])
def test_it_runs_only_where_the_session_says_it_is_remote(
    workspace: Workspace, plan_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str | None
) -> None:
    workspace.commit("feat(gateway): add the vm")
    plan_file.write_text("gateway-vm 1\n")
    if value is None:
        monkeypatch.delenv("CLAUDE_CODE_REMOTE")
    else:
        monkeypatch.setenv("CLAUDE_CODE_REMOTE", value)

    assert "only where CLAUDE_CODE_REMOTE is `true`" in refused(workspace, plan_file, capsys)


def test_a_branch_behind_the_base_is_refused(workspace: Workspace, plan_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace.commit("feat(gateway): add the vm")
    commit(workspace.upstream, "chore: move on", {"later.txt": "later\n"})
    plan_file.write_text("gateway-vm 1\n")

    assert "not on the tip of origin/main (1 commits of it are missing)" in refused(workspace, plan_file, capsys)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda work: (work / "base.txt").write_text("edited\n"), id="edited-file"),
        pytest.param(lambda work: (work / "new.txt").write_text("new\n"), id="untracked-file"),
        pytest.param(lambda work: [(work / "staged.txt").write_text("s\n"), git(work, "add", "staged.txt")], id="staged-file"),
    ],
)
def test_a_tree_with_changes_is_refused(workspace: Workspace, plan_file: Path, capsys: pytest.CaptureFixture[str], change) -> None:
    workspace.commit("feat(gateway): add the vm")
    change(workspace.work)
    plan_file.write_text("gateway-vm 1\n")

    said = refused(workspace, plan_file, capsys)

    assert said.startswith("deliver_series: the working tree has changes (")
    assert any(name in said for name in ("(base.txt", "(new.txt", "(staged.txt"))


def test_a_merge_is_refused(workspace: Workspace, plan_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    git(workspace.work, "switch", "-q", "-c", "side")
    workspace.commit("feat(gateway): on the side")
    git(workspace.work, "switch", "-q", "main")
    workspace.commit("feat(gateway): on the line")
    git(workspace.work, "merge", "-q", "--no-ff", "-m", message("chore: merge it"), "side")
    plan_file.write_text("gateway-vm 3 feat(gateway): all of it\n")

    assert "is a merge" in refused(workspace, plan_file, capsys)


@pytest.mark.parametrize(
    ("plan", "said"), [("a-b 1\n", "holds 1 commits and the branch has 2"), ("a-b 3 feat(x): y\n", "holds 3 commits and the branch has 2")]
)
def test_a_plan_that_does_not_account_for_every_commit_is_refused(
    workspace: Workspace, plan_file: Path, capsys: pytest.CaptureFixture[str], plan: str, said: str
) -> None:
    workspace.commit("feat(gateway): add the vm")
    workspace.commit("feat(gateway): add the router")
    plan_file.write_text(plan)

    assert said in refused(workspace, plan_file, capsys)


def test_no_commits_above_the_base_are_refused(workspace: Workspace, plan_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plan_file.write_text("gateway-vm 1\n")

    assert "holds 1 commits and the branch has 0" in refused(workspace, plan_file, capsys)


def test_the_series_file_is_not_written_inside_the_checkout(workspace: Workspace, plan_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace.commit("feat(gateway): add the vm")
    plan_file.write_text("gateway-vm 1\n")
    inside = workspace.work / "sub"
    inside.mkdir()
    (inside / ".gitkeep").write_text("")
    git(workspace.work, "add", "-A")
    git(workspace.work, "commit", "-q", "-m", message("chore: keep a directory"))

    assert main([str(plan_file), "--repo", str(workspace.work), "--out", str(inside), "--build-only"]) == 1

    assert "is inside the checkout" in capsys.readouterr().err
    assert sorted(path.name for path in inside.iterdir()) == [".gitkeep"]


def test_a_slug_of_a_series_not_merged_is_refused(workspace: Workspace, plan_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    earlier = tmp_path / "earlier.series"
    workspace.commit("feat(gateway): add the vm")
    plan_file.write_text("gateway-vm 1\n")
    assert deliver(workspace, plan_file) == 0
    [first] = series_files(workspace)
    first.rename(earlier)

    assert "already used" in refused(workspace, plan_file, capsys, "--after", str(earlier))


def test_a_binary_patch_is_refused(workspace: Workspace, plan_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace.commit("feat(gateway): add an image", files={"image.bin": bytes(range(256)) * 4})
    plan_file.write_text("gateway-vm 1\n")

    assert "encoded or binary" in refused(workspace, plan_file, capsys)


def test_a_text_file_that_mentions_a_binary_patch_is_not_one(workspace: Workspace, plan_file: Path) -> None:
    workspace.commit("feat(gateway): explain binaries", files={"notes.txt": "GIT binary patch\nBinary files a and b differ\n"})
    plan_file.write_text("gateway-vm 1\n")

    assert deliver(workspace, plan_file) == 0


def test_a_non_ascii_subject_is_refused_because_its_header_is_encoded(workspace: Workspace, plan_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace.commit("feat(gateway): add the vm — now")
    plan_file.write_text("gateway-vm 1\n")

    assert "encoded or binary" in refused(workspace, plan_file, capsys)


OTHER = ("Someone Else", "else@example.invalid")


@pytest.mark.parametrize(
    ("kwargs", "said"),
    [
        pytest.param({"identity": OTHER}, "is Someone Else <else@example.invalid>, not the maintainer", id="not-the-maintainers-identity"),
        pytest.param({"identity": BOT}, "not the maintainer", id="a-bots-author"),
        pytest.param({"committer": MAINTAINER}, "the committer is Maint Ainer <maint@example.invalid>, not the session's", id="the-maintainer-as-committer"),
        pytest.param(
            {"committer": ("Claude", "else@example.invalid")}, "not the session's Claude <noreply@anthropic.com>", id="the-sessions-name-with-another-email"
        ),
        pytest.param({"date": "2026-11-28T02:00:00+0000"}, "is not at +0800", id="utc-dates"),
        pytest.param({"text": message("Add the vm")}, "not Conventional Commits", id="subject-not-conventional"),
        pytest.param({"text": message("feat(gateway): Add the vm")}, "not Conventional Commits", id="subject-capitalised"),
        pytest.param({"text": message("feat(gateway): " + "word " * 15)}, "at most 72", id="subject-too-long"),
        pytest.param({"text": message("feat(gateway): add 0001a")}, "an id, a number or the slug", id="subject-with-an-id"),
        pytest.param({"text": message("feat(gateway): fix #12")}, "an id, a number or the slug", id="subject-with-a-number"),
        pytest.param({"text": message("feat(gateway): add gateway-vm")}, "an id, a number or the slug", id="subject-with-the-slug"),
        pytest.param({"text": "feat(gateway): add the vm\n\nSay what changed.\n"}, "exactly one trailer", id="no-trailer"),
        pytest.param(
            {"text": message("feat(gateway): add the vm", TRAILER, "Co-Authored-By: Other Model <noreply@anthropic.com>")},
            "exactly one trailer",
            id="two-model-trailers",
        ),
        pytest.param(
            {"text": message("feat(gateway): add the vm", "Co-Authored-By: Test Model <someone@example.com>")},
            "exactly one trailer",
            id="trailer-not-anthropic",
        ),
        pytest.param(
            {"text": message("feat(gateway): add the vm", TRAILER, "Signed-off-by: Maint Ainer <maint@example.invalid>")},
            "'Signed-off-by' is not allowed",
            id="other-trailer",
        ),
        pytest.param({"text": f"feat(gateway): add the vm\n\n{TRAILER}\n\nMore text after the trailer.\n"}, "exactly one trailer", id="trailer-not-last"),
        pytest.param({"text": message("feat(gateway): add the vm", TRAILER) + "\nhttps://claude.ai/code/session_abc123\n"}, "session link", id="session-link"),
    ],
)
def test_a_commit_without_the_commit_form_is_refused(
    workspace: Workspace, plan_file: Path, capsys: pytest.CaptureFixture[str], kwargs: dict, said: str
) -> None:
    workspace.commit("feat(gateway): add the vm", **kwargs)
    plan_file.write_text("gateway-vm 1\n")

    assert said in refused(workspace, plan_file, capsys)


def test_the_trailers_a_check_reads_go_beside_the_models(workspace: Workspace, plan_file: Path) -> None:
    text = message("feat(gateway): add the vm", TRAILER, "Plan-Confirmed: the-plan", "Editorial-Fix: yes")
    workspace.commit("feat(gateway): add the vm", text=text)
    plan_file.write_text("gateway-vm 1\n")

    assert deliver(workspace, plan_file) == 0


def test_every_commit_without_the_form_is_named_at_once(workspace: Workspace, plan_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace.commit("feat(gateway): add the vm", date="2026-11-28T02:00:00+0000")
    workspace.commit("feat(gateway): add the router")
    workspace.commit("feat(gateway): Add the switch")
    plan_file.write_text("gateway-vm 3 feat(gateway): all of it\n")

    said = refused(workspace, plan_file, capsys)

    assert "feat(gateway): add the vm" in said
    assert "feat(gateway): Add the switch" in said
    assert "feat(gateway): add the router" not in said
