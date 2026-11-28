"""The replay and the push stage, run for real by `land_series` and `git` on a toy repository, with stand-ins for `pre-commit` and `uv`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from _delivery_repo import Workspace, git
from deliver_series.__main__ import main
from deliver_series.form import Identity
from deliver_series.needs import NEEDS
from deliver_series.verify import Machine, VerifyError, fresh_clone, make_shim

HOOKS = {need.name: need.hooks for need in NEEDS}
DOCKER = "a Docker daemon"
TITLE = "feat(gateway): declare the production gateway"


def program(directory: Path, name: str, body: str) -> None:
    script = directory / name
    script.write_text(f"#!/bin/bash\n{body}\n")
    script.chmod(0o755)


@pytest.fixture
def calls(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `pre-commit` and a `uv` first on PATH that succeed, or fail where FAKE_FAIL says; each call is a line of the returned log."""
    log = tmp_path_factory.mktemp("calls") / "log"
    bin_dir = tmp_path_factory.mktemp("bin")
    program(
        bin_dir,
        "pre-commit",
        'echo "pre-commit $* | SKIP=${SKIP-} BASE=${CHECK_DOC_CHANGE_BASE-} AT=$(git log -1 --format=%s 2>/dev/null)" >> "$FAKE_LOG"\n'
        'case "${FAKE_FAIL-}:$*" in all:*--all-files*|push:*pre-push*) echo "a hook failed"; exit 1;; esac',
    )
    program(bin_dir, "uv", 'echo "uv $*" >> "$FAKE_LOG"\necho python_unit_tests=false')
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.delenv("SKIP", raising=False)
    return log


def met() -> dict:
    return {need.name: (lambda: None) for need in NEEDS}


def run_full(workspace: Workspace, plan: Path, *extra: str, probes: dict | None = None) -> int:
    return main([str(plan), "--repo", str(workspace.work), "--out", str(workspace.out), *extra], probes or met())


def pre_commit_calls(calls: Path) -> list[str]:
    return [line for line in calls.read_text().splitlines() if line.startswith("pre-commit")]


def test_a_series_is_replayed_and_handed_over(workspace: Workspace, plan_file: Path, calls: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = git(workspace.work, "rev-parse", "origin/main")
    workspace.commit("feat(gateway): add the vm")
    workspace.commit("docs(gateway): describe it")
    plan_file.write_text(f"gateway-vm 2 {TITLE}\n")

    assert run_full(workspace, plan_file) == 0

    out = capsys.readouterr().out
    assert f"Series file: {workspace.out / '0001-0001.series'}" in out
    assert "- 0001 gateway-vm: " + TITLE + " (2 commits)" in out
    assert 'uv run python -m land_series "$series" --repo .. --land' in out
    assert sorted(path.name for path in workspace.out.iterdir()) == ["0001-0001.log", "0001-0001.series"]
    made = pre_commit_calls(calls)
    assert made[0].startswith("pre-commit install |")
    assert f"pre-commit run --hook-stage pre-push --from-ref {base} --to-ref HEAD | SKIP= BASE={base} AT=docs(gateway): describe it" in made
    assert sum("--all-files" in line for line in made) == 2


def test_each_pull_request_runs_its_push_stage_from_the_commit_before_it(workspace: Workspace, plan_file: Path, calls: Path) -> None:
    workspace.commit("feat(gateway): add the vm")
    workspace.commit("feat(router): add the router")
    plan_file.write_text("gateway-vm 1\nrouter-vm 1\n")

    assert run_full(workspace, plan_file) == 0

    pushes = [line for line in pre_commit_calls(calls) if "pre-push" in line]
    assert [line.rsplit("AT=", 1)[1] for line in pushes] == ["feat(gateway): add the vm", "feat(router): add the router"]
    first_base, second_base = (line.split("--from-ref ")[1].split(" ")[0] for line in pushes)
    assert first_base != second_base


def test_a_hook_whose_need_is_missing_is_skipped_and_named(workspace: Workspace, plan_file: Path, calls: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace.commit("feat(gateway): add the vm")
    plan_file.write_text("gateway-vm 1\n")

    assert run_full(workspace, plan_file, probes={**met(), DOCKER: lambda: "no daemon"}) == 0

    out, err = capsys.readouterr()
    for hook in HOOKS[DOCKER]:
        assert f"- hook `{hook}` skipped: a Docker daemon: no daemon" in out
        assert f"skipping {hook}: a Docker daemon: no daemon" in err
    skip = ",".join(HOOKS[DOCKER])
    assert all(f"SKIP={skip} " in line for line in pre_commit_calls(calls)[1:])


def test_a_hook_whose_need_is_met_is_not_skipped(workspace: Workspace, plan_file: Path, calls: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace.commit("feat(gateway): add the vm")
    plan_file.write_text("gateway-vm 1\n")
    inherited = os.environ.setdefault("SKIP", "zizmor")
    assert inherited

    assert run_full(workspace, plan_file) == 0

    assert "- hook `" not in capsys.readouterr().out
    assert all("SKIP= " in line for line in pre_commit_calls(calls))


def test_a_commit_on_the_stop_list_is_replayed_only_when_its_patch_was_read(
    workspace: Workspace, plan_file: Path, calls: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace.commit("feat(tool): change a tool", files={"tools/tool.py": "x = 1\n"})
    plan_file.write_text("tool-change 1\n")

    assert run_full(workspace, plan_file) == 1

    assert "0001a (tools/tool.py)" in capsys.readouterr().err
    assert sorted(workspace.out.iterdir()) == []
    assert not calls.exists()

    assert run_full(workspace, plan_file, "--patches-read") == 0

    assert "- 0001a tool-change: tools/tool.py" in capsys.readouterr().out


@pytest.mark.parametrize(("fail", "said"), [("all", "the replay failed"), ("push", "pull request 0001 fails the push stage")])
def test_a_series_that_fails_a_stage_is_not_handed_over(
    workspace: Workspace, plan_file: Path, calls: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fail: str, said: str
) -> None:
    workspace.commit("feat(gateway): add the vm")
    plan_file.write_text("gateway-vm 1\n")
    monkeypatch.setenv("FAKE_FAIL", fail)

    assert run_full(workspace, plan_file) == 1

    err = capsys.readouterr().err
    assert said in err
    assert "a hook failed" in err
    assert "0001-0001.series" not in [path.name for path in workspace.out.iterdir()]


def test_the_command_refuses_a_base_that_moved_while_it_ran(workspace: Workspace, calls: Path) -> None:
    machine = Machine(Identity("Maint Ainer", "maint@example.invalid"), {}, None)

    with (
        pytest.raises(VerifyError, match=r"moved to .* while the series was built on"),
        fresh_clone(str(workspace.upstream), "origin/main", "0" * 40, machine, lambda _: None),
    ):
        pass


def test_no_shim_is_made_where_pre_commit_is_on_path(tmp_path: Path, calls: Path) -> None:
    assert make_shim(tmp_path) is None


def test_a_shim_runs_pre_commit_through_uvx_where_none_is_on_path(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path_factory.mktemp("bin")
    program(bin_dir, "uvx", "true")
    monkeypatch.setenv("PATH", str(bin_dir))
    shim_dir = tmp_path_factory.mktemp("shim")

    assert make_shim(shim_dir) == shim_dir
    assert (shim_dir / "pre-commit").read_text() == '#!/bin/bash\nexec uvx --python 3.14 pre-commit "$@"\n'
    assert os.access(shim_dir / "pre-commit", os.X_OK)


def test_a_machine_with_neither_pre_commit_nor_uvx_is_refused(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path_factory.mktemp("empty")))

    with pytest.raises(VerifyError, match="neither `pre-commit` nor `uvx`"):
        make_shim(tmp_path_factory.mktemp("shim"))
