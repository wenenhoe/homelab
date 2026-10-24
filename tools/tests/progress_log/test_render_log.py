"""The markdown a period's changes become, and the milestones summarised from them."""

from __future__ import annotations

from datetime import datetime

import pytest
from progress_log import render

WEEK, MONTH, PREV_MONTH = "2026-W42", "2026-10", "2026-09"


def unit(cat="built", *, pr=1, title="a thing", group="tools/", events=None, date="2026-10-14T10:00:00+08:00", kind="pr"):
    return {
        "cat": cat,
        "sha": f"{pr or 0:040x}",
        "date": date,
        "kind": kind,
        "pr": pr,
        "title": title,
        "type": "feat",
        "bot": cat == "dep",
        "group": "Dependency updates" if cat == "dep" else group,
        "events": events or [],
    }


class TestWeeks:
    @pytest.mark.parametrize(
        ("moment", "expected"),
        [
            pytest.param("2026-10-18T23:59:00+08:00", "2026-W42", id="sunday-night-is-the-old-week"),
            pytest.param("2026-10-19T00:00:00+08:00", "2026-W43", id="monday-morning-is-the-new-week"),
            pytest.param("2026-12-31T12:00:00+08:00", "2026-W53", id="year-end-week"),
            pytest.param("2027-01-01T12:00:00+08:00", "2026-W53", id="new-year-in-the-old-iso-week"),
        ],
    )
    def test_run_monday_to_sunday(self, moment, expected):
        assert render.week_key(datetime.fromisoformat(moment)) == expected

    def test_bounds_are_monday_and_sunday(self):
        start, end = render.week_bounds("2026-W43")
        assert (start.isoformat(), end.isoformat()) == ("2026-10-19", "2026-10-25")


class TestSummary:
    def test_a_project_opened_and_removed_in_the_span_is_churn_not_progress(self):
        units = [unit(events=[["project", "x", "opened (not-started)"], ["project", "x", "closed"]])]
        summary = render.summarise(units)
        assert (summary["closed"], summary["scoped"], summary["churn"]) == ([], [], 1)

    def test_a_project_that_finished_is_closed(self):
        summary = render.summarise([unit(events=[["project", "x", "building → done"], ["project", "x", "closed"]])])
        assert summary["closed"] == ["x"]

    def test_a_project_that_started_building_is_listed_once(self):
        units = [unit(events=[["project", "x", "opened (not-started)"], ["project", "x", "not-started → building"]])]
        summary = render.summarise(units)
        assert (summary["building"], summary["scoped"]) == (["x"], [])

    def test_an_accepted_decision_is_not_also_approved(self):
        events = [
            ["adr", "ADR 0001 r000 · x", "added (working)"],
            ["adr", "ADR 0001 r000 · x", "working → approved"],
            ["adr", "ADR 0001 r000 · x", "approved → accepted"],
        ]
        summary = render.summarise([unit(events=events)])
        assert (summary["adr_accepted"], summary["adr_approved"], summary["adr_new"]) == (["0001"], [], 1)

    def test_a_component_is_added_or_removed(self):
        summary = render.summarise([unit(events=[["component", "app a", "added"], ["component", "app b", "removed"]])])
        assert (summary["comp_added"], summary["comp_removed"]) == (["app a"], ["app b"])


class TestHeadline:
    def test_counts_each_category_and_the_dependency_updates_apart(self):
        units = [unit("built", pr=1), unit("built", pr=2), unit("planned", pr=3), unit("scope", pr=4), unit("dep", pr=5)]
        assert render.headline(units) == "**4 PRs** — 2 code · 1 docs · 1 project-doc edits · plus 1 dependency updates"

    def test_says_changes_when_some_have_no_pr(self):
        assert render.headline([unit(pr=None, kind="direct")]).startswith("**1 changes**")

    def test_a_week_with_nothing_notable_says_so(self):
        assert render.highlights([unit()]) == ["_No project, decision or component milestones._"]


class TestFiles:
    def test_a_week_file_lists_its_changes_under_their_theme(self, tmp_path):
        (tmp_path / "weeks").mkdir()
        render.render_week("2026-W42", [unit(pr=5, title="add <b>", group="Project: gatus")], "https://example.invalid/r", None, tmp_path)
        text = (tmp_path / "weeks/2026-W42.md").read_text()
        assert all(
            part in text
            for part in (
                "# 2026-W42 · 12 Oct to 18 Oct 2026",
                "**Project: gatus**",
                "[#5](https://example.invalid/r/pull/5) add &lt;b&gt;",
                "| Project: gatus | 1 |",
            )
        )

    def test_the_week_in_progress_is_marked(self, tmp_path):
        (tmp_path / "weeks").mkdir()
        render.render_week("2026-W42", [unit()], "u", "2026-W42", tmp_path)
        assert "*(in progress)*" in (tmp_path / "weeks/2026-W42.md").read_text()

    def test_dependency_updates_are_counted_not_listed(self, tmp_path):
        (tmp_path / "weeks").mkdir()
        render.render_week("2026-W42", [unit("dep", pr=8, title="bump zzz")], "u", None, tmp_path)
        text = (tmp_path / "weeks/2026-W42.md").read_text()
        assert ("bump zzz" in text, "1 dependency updates (Renovate) not listed" in text) == (False, True)

    def test_notes_written_under_the_marker_survive_a_rewrite(self, tmp_path):
        (tmp_path / "weeks").mkdir()
        path = tmp_path / "weeks/2026-W42.md"
        render.render_week("2026-W42", [unit()], "u", None, tmp_path)
        path.write_text(path.read_text().replace("_Notes:_", "My own words."))
        render.render_week("2026-W42", [unit(), unit(pr=2)], "u", None, tmp_path)
        assert path.read_text().endswith(f"{render.NOTES_MARK}\nMy own words.\n")

    def test_a_month_file_links_its_weeks(self, tmp_path):
        (tmp_path / "months").mkdir()
        weeks = {"2026-W42": {"units": [unit(date="2026-10-14T10:00:00+08:00")]}, "2026-W41": {"units": [unit(pr=2, date="2026-09-30T10:00:00+08:00")]}}
        render.render_month("2026-10", weeks, tmp_path)
        text = (tmp_path / "months/2026-10.md").read_text()
        assert ("# October 2026" in text, f"[{WEEK}](../weeks/{WEEK}.md)" in text, "2026-W41" in text) == (True, True, False)

    def test_the_index_links_recent_weeks_and_every_month(self, tmp_path):
        weeks = {"2026-W42": {"units": [unit(date="2026-10-14T10:00:00+08:00")]}, "2026-W36": {"units": [unit(pr=2, date="2026-09-02T10:00:00+08:00")]}}
        render.render_index(weeks, "abcdef0123", tmp_path)
        text = (tmp_path / "README.md").read_text()
        assert all(
            part in text
            for part in ("up to `abcdef0`", f"[{WEEK}](weeks/{WEEK}.md)", f"[{MONTH}](months/{MONTH}.md)", f"[{PREV_MONTH}](months/{PREV_MONTH}.md)")
        )
