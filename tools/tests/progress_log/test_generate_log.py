"""Writing the log from a repository: resuming, rebuilding, and keeping hand-written notes."""

from __future__ import annotations

import json

import pytest
from _progress_fixtures import project_doc, project_path, snapshot
from progress_log import generate, render

W41, W42, W43 = "2026-10-06T10:00:00+0800", "2026-10-14T10:00:00+0800", "2026-10-20T10:00:00+0800"


def grow(repo, *, upto: int) -> list[str]:
    """Three PRs in three weeks (the first week also holds the repository's first commit); returns the head after each of the first `upto`."""
    steps = [
        ("feat-gatus", "feat(gatus): add it", {"docker/gatus/compose.yaml": "x", project_path("gatus"): project_doc("not-started")}, W41),
        ("docs-build", "docs: build it", {project_path("gatus"): project_doc("building")}, W42),
        ("fix-gatus", "fix(gatus): repair it", {"docker/gatus/compose.yaml": "y"}, W43),
    ]
    return [repo.pr(number, *step) for number, step in enumerate(steps[:upto], start=1)]


def add_note(out, week: str, text: str) -> None:
    path = out / "weeks" / f"{week}.md"
    path.write_text(path.read_text().replace("_Notes:_", text))


class TestFullBuild:
    def test_writes_a_file_per_week_and_month_an_index_and_the_state(self, repo, out):
        (head,) = grow(repo, upto=1)
        generate.generate(repo.path, out)
        assert (sorted(snapshot(out)), json.loads((out / "state.json").read_text())) == (
            ["README.md", "data/2026-W41.json", "months/2026-10.md", "state.json", "weeks/2026-W41.md"],
            {"last_sha": head, "current_week": "2026-W41"},
        )

    def test_a_change_is_filed_in_the_week_of_its_singapore_date(self, repo, out):
        repo.direct("docs: just before midnight UTC on a Sunday", {"docs/a.md": "x"}, "2026-10-18T23:30:00+0000")
        generate.generate(repo.path, out)
        assert "weeks/2026-W43.md" in snapshot(out)

    def test_an_empty_range_still_records_the_head(self, repo, out):
        generate.generate(repo.path, out, head_rev=repo.root)
        assert json.loads((out / "state.json").read_text())["last_sha"] == repo.root


class TestResume:
    def test_resuming_gives_the_same_files_as_rebuilding_from_scratch(self, repo, out, tmp_path_factory):
        heads = grow(repo, upto=1)
        generate.generate(repo.path, out, head_rev=heads[0])
        heads = grow_more(repo)
        resumed = generate.generate(repo.path, out)
        rebuilt_out = tmp_path_factory.mktemp("rebuilt")
        generate.generate(repo.path, rebuilt_out, full=True)
        assert (snapshot(out), "incremental" in resumed) == (snapshot(rebuilt_out), True)

    def test_resuming_reads_only_what_is_new(self, repo, out):
        grow(repo, upto=2)
        generate.generate(repo.path, out)
        repo.pr(3, "fix-gatus", "fix(gatus): repair it", {"docker/gatus/compose.yaml": "y"}, W43)
        assert generate.generate(repo.path, out).startswith("read 1 new changes (incremental from ")

    def test_running_again_with_nothing_new_changes_nothing(self, repo, out):
        grow(repo, upto=3)
        generate.generate(repo.path, out)
        before = snapshot(out)
        generate.generate(repo.path, out)
        assert snapshot(out) == before

    def test_a_week_that_is_over_is_left_alone_with_its_notes(self, repo, out):
        grow(repo, upto=2)
        generate.generate(repo.path, out)
        add_note(out, "2026-W41", "Remember this week.")
        before = (out / "weeks/2026-W41.md").read_bytes()
        repo.pr(3, "fix-gatus", "fix(gatus): repair it", {"docker/gatus/compose.yaml": "y"}, W43)
        generate.generate(repo.path, out)
        assert (out / "weeks/2026-W41.md").read_bytes() == before

    def test_the_week_that_was_in_progress_loses_its_marker_once_a_newer_one_starts(self, repo, out):
        grow(repo, upto=2)
        generate.generate(repo.path, out)
        marked = "(in progress)" in (out / "weeks/2026-W42.md").read_text()
        repo.pr(3, "fix-gatus", "fix(gatus): repair it", {"docker/gatus/compose.yaml": "y"}, W43)
        generate.generate(repo.path, out)
        assert (marked, "(in progress)" in (out / "weeks/2026-W42.md").read_text()) == (True, False)


class TestRebuild:
    def test_a_recorded_commit_that_is_not_in_main_triggers_a_full_rebuild_that_keeps_notes(self, repo, out, tmp_path_factory):
        grow(repo, upto=3)
        generate.generate(repo.path, out)
        add_note(out, "2026-W42", "Kept across a rebuild.")
        repo.git("checkout", "-q", "-b", "side")
        stray = repo.direct("docs: only on a side branch", {"docs/side.md": "x"}, W43)
        repo.git("checkout", "-q", "main")
        state = json.loads((out / "state.json").read_text())
        (out / "state.json").write_text(json.dumps({**state, "last_sha": stray}))
        message = generate.generate(repo.path, out)
        fresh = tmp_path_factory.mktemp("fresh")
        generate.generate(repo.path, fresh)
        add_note(fresh, "2026-W42", "Kept across a rebuild.")
        assert (" (full)" in message, snapshot(out)) == (True, snapshot(fresh))

    def test_full_ignores_the_recorded_commit(self, repo, out):
        grow(repo, upto=2)
        generate.generate(repo.path, out)
        assert generate.generate(repo.path, out, full=True).startswith("read 3 new changes (full)")

    def test_a_week_with_no_changes_left_after_a_rebuild_keeps_no_stale_data(self, repo, out):
        grow(repo, upto=3)
        generate.generate(repo.path, out)
        (out / "data/2026-W99.json").write_text("{}")
        generate.generate(repo.path, out, full=True)
        assert (out / "data/2026-W99.json").exists() is False


class TestCommandLine:
    def test_writes_the_log_and_reports_what_it_read(self, repo, out, capsys):
        grow(repo, upto=1)
        status = generate.main(["--repo", str(repo.path), "--out", str(out), "--repo-url", "https://example.invalid/r"])
        printed = capsys.readouterr().out
        assert (status, printed.startswith("read 2 new changes (full)"), "https://example.invalid/r/pull/1" in (out / "weeks/2026-W41.md").read_text()) == (
            0,
            True,
            True,
        )

    def test_a_missing_repository_is_an_error(self, out, tmp_path_factory):
        with pytest.raises(Exception, match="rev-parse"):
            generate.generate(tmp_path_factory.mktemp("nothing"), out)


def grow_more(repo) -> list[str]:
    return [
        repo.pr(2, "docs-build", "docs: build it", {project_path("gatus"): project_doc("building")}, W42),
        repo.pr(3, "fix-gatus", "fix(gatus): repair it", {"docker/gatus/compose.yaml": "y"}, W43),
    ]


def test_the_notes_marker_is_what_a_week_file_ends_with(repo, out):
    grow(repo, upto=1)
    generate.generate(repo.path, out)
    assert (out / "weeks/2026-W41.md").read_text().endswith(f"{render.NOTES_MARK}\n_Notes:_\n")
