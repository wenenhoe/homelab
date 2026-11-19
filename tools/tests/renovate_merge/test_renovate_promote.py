from pathlib import Path

import pytest
from _bodies import BREAKING_NOTES, body
from _promote_repo import Remote, make_remote
from conftest import FakeGitHub
from renovate_merge import promote
from renovate_merge.promote import Batch, Entry, PromoteError

MARKERS = ("promotion-checklist:start", "promotion-checklist:end")


@pytest.fixture
def remote(tmp_path: Path) -> Remote:
    return make_remote(tmp_path)


def renovate_pull(github: FakeGitHub, title: str = "chore(deps): update example/tool", **kwargs: object) -> int:
    return github.add_pull(title=title, state_name="MERGED", **kwargs)


def go(remote: Remote, confirm: promote.Confirm = lambda _: True, dry_run: bool = False) -> tuple[Batch, promote.Opened | None]:
    return promote.promote(remote.clone, confirm, dry_run=dry_run, sleep=lambda _: None)


class TestHistory:
    def test_lists_the_pull_requests_merged_into_the_source_and_the_commits_made_on_it(self, remote: Remote) -> None:
        remote.merge_pull(7, "renovate/b")
        remote.merge_pull(5, "renovate/a")
        remote.commit("maintenance", "chore(deps): bump a pin")
        remote.push()
        promote.fetch(remote.clone)

        assert promote.history(remote.clone) == ([(5, "wenenhoe/renovate/a"), (7, "wenenhoe/renovate/b")], ["chore(deps): bump a pin"])

    def test_leaves_out_a_merge_of_main_into_the_source_and_what_main_already_holds(self, remote: Remote) -> None:
        remote.merge_pull(5, "renovate/a")
        remote.commit("main", "fix: something on main")
        remote.sync("maintenance")
        remote.merge_pull(6, "renovate/b")
        remote.push()
        promote.fetch(remote.clone)

        assert promote.history(remote.clone) == ([(5, "wenenhoe/renovate/a"), (6, "wenenhoe/renovate/b")], [])

    def test_leaves_out_a_pull_request_already_promoted(self, remote: Remote) -> None:
        remote.merge_pull(5, "renovate/a")
        remote.sync("main", "maintenance")
        remote.merge_pull(6, "renovate/b")
        remote.push()
        promote.fetch(remote.clone)

        assert promote.history(remote.clone) == ([(6, "wenenhoe/renovate/b")], [])

    def test_reads_what_the_remote_holds_and_not_what_the_clone_last_saw(self, remote: Remote) -> None:
        remote.merge_pull(5, "renovate/a")
        remote.push()

        assert promote.history(remote.clone) == ([], [])
        promote.fetch(remote.clone)
        assert promote.history(remote.clone)[0] == [(5, "wenenhoe/renovate/a")]


class TestBatch:
    def test_reads_each_renovate_pull_request_for_its_level_and_matches(self, remote: Remote, github: FakeGitHub) -> None:
        remote.merge_pull(1, "renovate/a")
        remote.merge_pull(2, "renovate/b")
        remote.push()
        renovate_pull(github, branch="renovate/a")
        renovate_pull(github, title="chore(deps): update example/tool to v2", description=body("example/tool", "1.9.9", "2.0.0", BREAKING_NOTES))
        promote.fetch(remote.clone)

        found = promote.batch(remote.clone)

        assert found.entries == [
            Entry(1, "chore(deps): update example/tool", "none", ()),
            Entry(2, "chore(deps): update example/tool to v2", "breaking", ("breaking", "removal", "warning")),
        ]

    def test_gives_a_pull_request_that_is_not_renovates_no_level(self, remote: Remote, github: FakeGitHub) -> None:
        remote.merge_pull(1, "docs/a")
        remote.push()
        renovate_pull(github, title="docs: a change", login="someone", branch="docs/a")
        promote.fetch(remote.clone)

        assert promote.batch(remote.clone).entries == [Entry(1, "docs: a change")]

    def test_names_a_pull_request_github_no_longer_lists_by_its_branch(self, remote: Remote, github: FakeGitHub) -> None:
        remote.merge_pull(99, "renovate/gone")
        remote.push()
        promote.fetch(remote.clone)

        assert promote.batch(remote.clone).entries == [Entry(99, "wenenhoe/renovate/gone")]

    def test_refuses_when_the_source_holds_nothing_the_target_lacks(self, remote: Remote, github: FakeGitHub) -> None:
        with pytest.raises(PromoteError, match="maintenance holds nothing that main lacks"):
            promote.batch(remote.clone)


class TestBody:
    def test_has_a_row_per_pull_request_with_the_title_as_code(self) -> None:
        text = promote.body(Batch([Entry(1, "update `@types/node` | v2", "breaking", ("breaking", "warning")), Entry(2, "docs: x")], []))

        assert "| #1 | `` update `@types/node` \\| v2 `` | breaking | breaking, warning |" in text
        assert "| #2 | ` docs: x ` | — | — |" in text

    def test_carries_no_marker_of_the_promotion_checklist(self) -> None:
        text = promote.body(Batch([Entry(1, "x", "none")], ["a commit"]))

        assert not any(marker in text for marker in MARKERS)

    def test_lists_the_other_commits_up_to_a_limit(self) -> None:
        commits = [f"commit {number}" for number in range(promote.MAX_OTHER_COMMITS + 3)]

        text = promote.body(Batch([], commits))

        assert "- ` commit 9 `" in text
        assert "commit 10" not in text
        assert "- and 3 more" in text

    def test_says_how_to_merge_it(self) -> None:
        assert "with a merge commit, using the bypass, and never squash" in promote.body(Batch([Entry(1, "x")], []))

    @pytest.mark.parametrize(
        ("entries", "title"),
        [
            pytest.param([Entry(1, "a")], "chore(deps): promote 1 update from maintenance", id="one"),
            pytest.param([Entry(1, "a"), Entry(2, "b")], "chore(deps): promote 2 updates from maintenance", id="several"),
            pytest.param([], "chore(deps): promote maintenance", id="commits-only"),
        ],
    )
    def test_title(self, entries: list[Entry], title: str) -> None:
        assert Batch(entries, ["c"]).title == title

    def test_describe_counts_the_pull_requests_at_each_level(self) -> None:
        found = Batch([Entry(1, "a", "none"), Entry(2, "b", "none"), Entry(3, "c", "breaking"), Entry(4, "d")], [])

        assert promote.describe(found) == [found.title, "  1  breaking", "  2  none", "  1  not Renovate's"]


class TestPromote:
    def prepare(self, remote: Remote, github: FakeGitHub) -> None:
        remote.merge_pull(1, "renovate/a")
        remote.merge_pull(2, "renovate/b")
        remote.push()
        renovate_pull(github, branch="renovate/a")
        renovate_pull(github, branch="renovate/b")

    def test_opens_a_pull_request_from_the_source_into_the_target_and_merges_nothing(self, remote: Remote, github: FakeGitHub) -> None:
        self.prepare(remote, github)

        found, opened = go(remote)

        [created] = github.created()
        assert (created["baseRefName"], created["headRefName"], created["title"]) == ("main", "maintenance", "chore(deps): promote 2 updates from maintenance")
        assert created["body"] == promote.body(found)
        assert opened == promote.Opened(created["url"], created=True)
        assert github.merged() == []
        assert not any(call[:2] == ["pr", "merge"] for call in github.calls())

    def test_leaves_a_pull_request_that_is_open_already_as_it_is(self, remote: Remote, github: FakeGitHub) -> None:
        self.prepare(remote, github)
        github.add_pull(title="chore(deps): promote", branch="maintenance", base="main", login="someone")

        _, opened = go(remote, confirm=lambda _: pytest.fail("nothing is opened, so nothing is asked"))

        assert opened == promote.Opened("https://example.test/pull/3", created=False)
        assert github.created() == []
        assert not any(call[:2] in (["pr", "edit"], ["pr", "create"]) for call in github.calls())

    def test_a_pull_request_from_a_fork_of_the_same_name_is_not_the_open_one(self, remote: Remote, github: FakeGitHub) -> None:
        self.prepare(remote, github)
        github.add_pull(branch="maintenance", base="main", fork=True)

        _, opened = go(remote)

        assert opened is not None
        assert opened.created

    def test_a_dry_run_opens_nothing_and_asks_nothing(self, remote: Remote, github: FakeGitHub) -> None:
        self.prepare(remote, github)

        found, opened = go(remote, confirm=lambda _: pytest.fail("a dry run asks nothing"), dry_run=True)

        assert opened is None
        assert len(found.entries) == 2
        assert github.created() == []

    def test_opens_nothing_when_not_confirmed(self, remote: Remote, github: FakeGitHub) -> None:
        self.prepare(remote, github)

        with pytest.raises(PromoteError, match="not confirmed; no pull request was opened"):
            go(remote, confirm=lambda _: False)

        assert github.created() == []

    def test_confirmation_is_given_the_batch(self, remote: Remote, github: FakeGitHub) -> None:
        self.prepare(remote, github)
        asked: list[int] = []

        go(remote, confirm=lambda found: asked.append(len(found.entries)) or True)

        assert asked == [2]

    def test_stops_when_gh_is_not_logged_in(self, remote: Remote, github: FakeGitHub) -> None:
        self.prepare(remote, github)
        state = github.state()
        state["logged_out"] = True
        github.save(state)

        with pytest.raises(PromoteError, match="gh auth login"):
            go(remote)

        assert github.created() == []

    def test_opens_for_commits_made_straight_on_the_source_branch(self, remote: Remote, github: FakeGitHub) -> None:
        remote.commit("maintenance", "chore(deps): bump a pin")
        remote.push()

        found, opened = go(remote)

        assert found.entries == []
        assert opened is not None
        assert github.created()[0]["title"] == "chore(deps): promote maintenance"
