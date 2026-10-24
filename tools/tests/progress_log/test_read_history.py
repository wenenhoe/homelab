"""Reading first-parent history into one record per change."""

from __future__ import annotations

import pytest
from _progress_fixtures import decision_path, project_doc, project_path
from progress_log import history

MON = "2026-10-12T10:00:00+0800"


def units(repo):
    """The changes made after the repository's first commit."""
    return history.parse_units(repo.path, [f"{repo.root}..HEAD"])


class TestRecords:
    def test_a_pr_merge_takes_its_title_from_the_merge_body(self, repo):
        repo.pr(7, "feat-gatus", "feat(gatus): add the status page", {"docker/gatus/compose.yaml": "x"}, MON)
        (unit,) = units(repo)
        assert (unit["pr"], unit["kind"], unit["title"], unit["type"], unit["cat"]) == (7, "pr", "add the status page", "feat", "built")

    def test_a_merge_with_no_body_falls_back_to_the_branch_name(self, repo):
        repo.git("checkout", "-q", "-b", "fix-broken-link")
        repo.write({"docs/a.md": "x"})
        repo.git("add", "-A")
        repo.git("commit", "-q", "-m", "wip", when=MON)
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #3 from wenenhoe/fix-broken-link", "fix-broken-link", when=MON)
        (merge,) = units(repo)
        assert (merge["title"], merge["type"]) == ("broken link", "fix")

    def test_a_direct_commit_is_a_change_with_no_pr(self, repo):
        repo.direct("docs: first notes", {"docs/a.md": "x"}, MON)
        (unit,) = units(repo)
        assert (unit["pr"], unit["kind"], unit["title"], unit["type"]) == (None, "direct", "first notes", "docs")

    def test_dates_are_in_singapore_time(self, repo):
        repo.direct("docs: late", {"docs/a.md": "x"}, "2026-10-18T23:30:00+0000")
        (unit,) = units(repo)
        assert unit["date"] == "2026-10-19T07:30:00+08:00"

    def test_a_renovate_branch_is_a_dependency_update(self, repo):
        repo.pr(9, "renovate/docker-gatus-1.x", "chore(deps): update gatus", {"docker/gatus/compose.yaml": "x"}, MON)
        (unit,) = units(repo)
        assert (unit["bot"], unit["cat"], unit["group"]) == (True, "dep", "Dependency updates")

    def test_changes_come_oldest_first(self, repo):
        repo.pr(1, "feat-a", "feat: a", {"docs/a.md": "1"}, MON)
        repo.pr(2, "feat-b", "feat: b", {"docs/b.md": "1"}, "2026-10-13T10:00:00+0800")
        assert [unit["pr"] for unit in units(repo)] == [1, 2]

    def test_a_bad_revision_is_an_error(self, repo):
        repo.direct("docs: a", {"docs/a.md": "x"}, MON)
        with pytest.raises(history.GitError, match="rev-parse"):
            history.git(repo.path, "rev-parse", "no-such-rev")


class TestEvents:
    def test_a_project_is_opened_changed_and_closed(self, repo, subtests):
        repo.pr(1, "docs-open", "docs: open", {project_path("gatus"): project_doc("not-started")}, MON)
        repo.pr(2, "docs-build", "docs: build", {project_path("gatus"): project_doc("building")}, MON)
        repo.pr(3, "docs-close", "docs: close", {project_path("gatus"): None}, MON)
        events = [unit["events"] for unit in units(repo)]
        for index, expected in enumerate([["opened (not-started)"], ["not-started → building"], ["closed"]]):
            with subtests.test(change=index + 1):
                assert [event[2] for event in events[index]] == expected

    def test_an_edit_that_leaves_the_status_alone_is_no_event(self, repo):
        repo.pr(1, "docs-open", "docs: open", {project_path("gatus"): project_doc("building")}, MON)
        repo.pr(2, "docs-edit", "docs: edit", {project_path("gatus"): project_doc("building") + "more\n"}, MON)
        assert units(repo)[1]["events"] == []

    def test_a_decision_revision_is_added_and_approved(self, repo):
        path = decision_path("0042", "thing")
        repo.pr(1, "docs-adr", "docs: adr", {path: project_doc("working")}, MON)
        repo.pr(2, "docs-approve", "docs: approve", {path: project_doc("approved")}, MON)
        first, second = (unit["events"] for unit in units(repo))
        assert ([event[2] for event in first], [event[2] for event in second], first[0][1]) == (
            ["added (working)"],
            ["working → approved"],
            "ADR 0042 r000 · thing",
        )

    def test_a_component_is_added_then_removed(self, repo):
        repo.pr(1, "feat-a", "feat: a", {"docker/gatus/compose.yaml": "x"}, MON)
        repo.pr(2, "feat-b", "feat: b", {"docker/gatus/compose.yaml": None}, MON)
        added, removed = (unit["events"] for unit in units(repo))
        assert (added, removed) == ([["component", "app gatus", "added"]], [["component", "app gatus", "removed"]])

    def test_a_component_deleted_and_added_in_one_change_is_a_move_not_an_event(self, repo):
        repo.pr(1, "feat-a", "feat: a", {"docker/gatus/compose.yaml": "x"}, MON)
        repo.pr(2, "feat-b", "feat: b", {"docker/gatus/compose.yaml": None, "docker/gatus/compose.yml": "x"}, MON)
        assert units(repo)[1]["events"] == []
