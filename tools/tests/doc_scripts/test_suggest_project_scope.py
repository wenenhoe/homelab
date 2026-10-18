"""Tests for suggest_project_scope.py. The tool reads tracked files and runs `git grep`, so the
tests that need a tree use a real temporary git repository. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _doc_fixtures import GitRepo, revision, write_doc
from doc_scripts import suggest_project_scope as cli

DOC = "docs/projects/p.md"
NIST = "docs/topics/engineering/nist-800-53-alignment.md"


def body(in_line: str = "In: the `src/app/` role and [the topic](../topics/app.md).", not_in: str = "Not in: `src/other/thing.py`.") -> str:
    return f"""# P

## Scope

{in_line}

{not_in}

## Execution plan

| # | Stage | Status | Exit condition |
| :-: | :--- | :--- | :--- |
| 1 | Build | Not started | `src/app/tasks.yaml` renders |

## Acceptance criteria

- [ ] Nothing names Kuma.

## Agent handoff

- **Relevant files and interfaces:** `src/reads/only.py`

## Risks

- `src/risk/only.py` may move.
"""


def front(**extra) -> dict:
    return {"id": "PROJ-p", "title": "p", "type": "project", "status": "building", "summary": "s", **extra}


@pytest.fixture
def repo(root: Path) -> GitRepo:
    repo = GitRepo(root, cli)
    repo.git("init", "-q")
    repo.git("checkout", "-q", "-b", "main")
    write_doc(root, DOC, front(), body())
    for rel in ("src/app/tasks.yaml", "src/app/handlers.yaml", "src/apple/x.yaml", "src/other/thing.py", "src/reads/only.py", "src/risk/only.py"):
        repo.write(rel, "x = 1\n")
    repo.write("docs/topics/app.md", "# App\n")
    repo.commit("base")
    return repo


def report(repo: GitRepo, *terms: str) -> cli.Report:
    return cli.build_report(repo.root, DOC, list(terms))


def entries(findings: list[cli.Finding]) -> list[str]:
    return [f.entry for f in findings]


class TestStatedChanges:
    def test_reads_scope_without_not_in_plus_the_plan_and_criteria(self):
        text = cli.stated_changes(body())
        assert "`src/app/`" in text
        assert "`src/app/tasks.yaml`" in text
        assert "Kuma" in text

    @pytest.mark.parametrize("left_out", ["src/other/thing.py", "src/reads/only.py", "src/risk/only.py"], ids=["not-in", "agent-handoff", "risks"])
    def test_leaves_out_what_the_project_does_not_change(self, left_out):
        assert left_out not in cli.stated_changes(body())

    def test_a_not_in_paragraph_that_is_the_last_thing_in_scope_is_dropped(self):
        text = "## Scope\n\nIn: `a/b.py`.\n\nNot in: `c/d.py`.\n"
        assert "c/d.py" not in cli.stated_changes(text)
        assert "a/b.py" in cli.stated_changes(text)


class TestNamedPatterns:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("the `src/app/` role", ["src/app/"]),
            ("`./src/app.py`", ["src/app.py"]),
            ("`docs/projects/README.md#scope`", ["docs/projects/README.md"]),
            ("`src/*/thing.py`", ["src/*/thing.py"]),
            ("`git grep -l x/y`", []),
            ("`POST=1` and `main`", []),
            ("`https://example.com/a/b` and `/abs/path` and `~/home/x`", []),
            ("`a/b.py` and `a/b.py` again", ["a/b.py"]),
        ],
        ids=["dir", "dot-slash", "anchor", "glob", "has-spaces", "no-slash", "not-repo-relative", "repeated"],
    )
    def test_code_spans(self, text, expected):
        assert cli.named_patterns(text, DOC) == expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("[t](../topics/app.md)", ["docs/topics/app.md"]),
            ("[t](../topics/app.md#heading)", ["docs/topics/app.md"]),
            ("[t](sibling.md)", ["docs/projects/sibling.md"]),
            ("[t](https://example.com/x.md)", []),
            ("[t](/abs.md)", []),
            ("[t](../../../outside.md)", []),
        ],
        ids=["relative", "anchor", "sibling", "url", "absolute", "outside-the-repo"],
    )
    def test_link_targets_resolve_against_the_doc(self, text, expected):
        assert cli.named_patterns(text, DOC) == expected


class TestFilesNamed:
    TRACKED = ("src/app/a.py", "src/app/sub/b.py", "src/apple/c.py", "src/app.py", "tools/x/test_a.py")

    @pytest.mark.parametrize(
        ("pattern", "expected"),
        [
            ("src/app.py", ["src/app.py"]),
            ("src/app/", ["src/app/a.py", "src/app/sub/b.py"]),
            ("src/app", ["src/app/a.py", "src/app/sub/b.py"]),
            ("src/*/a.py", ["src/app/a.py"]),
            ("tools/**/test_*.py", ["tools/x/test_a.py"]),
            ("src/missing/", []),
        ],
        ids=["file", "dir-trailing-slash", "dir-bare", "glob", "recursive-glob", "nothing"],
    )
    def test_matches(self, pattern, expected):
        assert cli.files_named(pattern, list(self.TRACKED)) == expected

    @pytest.mark.parametrize(
        ("pattern", "entry"),
        [("src/app.py", "src/app.py"), ("src/app/", "src/app/**"), ("src/app", "src/app/**"), ("src/*/a.py", "src/*/a.py")],
        ids=["file", "dir-trailing-slash", "dir-bare", "glob"],
    )
    def test_entry_for(self, pattern, entry):
        assert cli.entry_for(pattern, list(self.TRACKED)) == entry


class TestNamed:
    def test_a_named_directory_becomes_a_glob_entry_covering_the_files_it_holds(self, repo):
        found = {f.entry: f for f in report(repo).named}
        assert found["src/app/**"].files == ("src/app/handlers.yaml", "src/app/tasks.yaml")
        assert "2 files" in found["src/app/**"].why

    def test_a_linked_file_is_named_by_its_target(self, repo):
        assert "docs/topics/app.md" in entries(report(repo).named)

    def test_a_directory_does_not_take_in_a_sibling_that_shares_its_prefix(self, repo):
        assert all("src/apple/x.yaml" not in f.files for f in report(repo).named)

    def test_what_the_scope_leaves_out_is_not_suggested(self, repo):
        files = {f for finding in report(repo).named for f in finding.files}
        assert not files & {"src/other/thing.py", "src/reads/only.py", "src/risk/only.py"}

    def test_a_covered_file_is_not_reported(self, repo):
        write_doc(repo.root, DOC, front(allowed_paths=["src/app/**"]), body())
        assert entries(report(repo).named) == ["docs/topics/app.md"]

    def test_decision_history_and_implicit_paths_are_never_suggested(self, repo):
        revision(repo.root, "0001-x", 0)
        repo.write("docs/projects/sibling.md", "# Sibling\n")
        repo.commit("an ADR and a sibling project doc")
        write_doc(repo.root, DOC, front(), body(in_line="In: [the ADR](../decisions/0001-x/revision-000.md) and [a sibling](sibling.md)."))
        assert entries(report(repo).named) == ["src/app/tasks.yaml"]  # only what the plan row names

    def test_a_path_that_matches_no_tracked_file_is_ignored(self, repo):
        write_doc(repo.root, DOC, front(), body(in_line="In: a new `src/brand-new/` role."))
        assert entries(report(repo).named) == ["src/app/tasks.yaml"]  # only what the plan row names

    def test_a_glob_the_doc_names_is_kept_as_written(self, repo):
        write_doc(repo.root, DOC, front(), body(in_line="In: `src/*/thing.py`."))
        found = {f.entry: f for f in report(repo).named}
        assert found["src/*/thing.py"].files == ("src/other/thing.py",)


class TestExempt:
    def test_lists_the_decision_and_the_revision_it_supersedes(self, repo):
        revision(repo.root, "0001-x", 0)
        revision(repo.root, "0001-x", 1, supersedes=0)
        repo.commit("a successor revision")
        write_doc(repo.root, DOC, front(decision="ADR-0001/1"), body())
        assert report(repo).exempt == {"docs/decisions/0001-x/revision-001.md": "decision", "docs/decisions/0001-x/revision-000.md": "superseded"}

    def test_is_empty_for_a_project_with_no_decision(self, repo):
        assert report(repo).exempt == {}


class TestClosing:
    def test_a_file_that_names_the_project_doc_is_reported(self, repo):
        repo.write("docs/topics/other.md", "See [the project](../projects/p.md).\n")
        repo.commit("a topic doc that links the project")
        found = report(repo).closing
        assert entries(found) == ["docs/topics/other.md"]
        assert "closing it edits this file" in found[0].why

    def test_the_project_doc_and_the_generated_views_are_not_reported(self, repo):
        repo.write("docs/projects/README.md", "| [`p.md`](p.md) |\n[p](projects/p.md)\n")
        repo.write("docs/project-planning.md", "[p](projects/p.md)\n")
        repo.write("docs/projects/p-notes.md", "[p](projects/p.md)\n")
        repo.commit("indexes and a sibling that name the project")
        assert report(repo).closing == []

    def test_a_decision_revision_that_names_the_project_is_reported(self, repo):
        revision(repo.root, "0002-y", 0, body="Built by [the project](../../projects/p.md).\n")
        repo.commit("an ADR that links the project")
        assert entries(report(repo).closing) == ["docs/decisions/0002-y/revision-000.md"]

    def test_the_decision_revision_the_project_implements_is_exempt_even_when_it_names_the_project(self, repo):
        revision(repo.root, "0001-x", 0, body="Built by [the project](../../projects/p.md).\n")
        repo.commit("the implemented ADR links the project")
        write_doc(repo.root, DOC, front(decision="ADR-0001/0"), body())
        assert report(repo).closing == []

    @pytest.fixture
    def superseding(self, repo) -> GitRepo:
        revision(repo.root, "0001-x", 0)
        revision(repo.root, "0001-x", 1, supersedes=0)
        write_doc(repo.root, DOC, front(decision="ADR-0001/1"), body())
        return repo

    def test_the_nist_page_is_reported_when_it_links_the_revision_the_close_supersedes(self, superseding):
        superseding.write(NIST, "| AC-6 | [ADR 0001](../../decisions/0001-x/revision-000.md) |\n")
        superseding.commit("the NIST page links the original")
        found = report(superseding).closing
        assert entries(found) == [NIST]
        assert "revision-000.md" in found[0].why

    def test_the_nist_page_is_not_reported_when_it_links_only_the_successor(self, superseding):
        superseding.write(NIST, "| AC-6 | [ADR 0001](../../decisions/0001-x/revision-001.md) |\n")
        superseding.commit("the NIST page links the successor")
        assert report(superseding).closing == []

    def test_the_nist_page_is_not_reported_when_the_project_supersedes_nothing(self, repo):
        revision(repo.root, "0001-x", 0)
        repo.write(NIST, "| AC-6 | [ADR 0001](../../decisions/0001-x/revision-000.md) |\n")
        repo.commit("the NIST page links an original nothing supersedes")
        write_doc(repo.root, DOC, front(decision="ADR-0001/0"), body())
        assert report(repo).closing == []

    def test_the_nist_page_is_not_reported_when_the_scope_covers_it(self, superseding):
        superseding.write(NIST, "| AC-6 | [ADR 0001](../../decisions/0001-x/revision-000.md) |\n")
        superseding.commit("the NIST page links the original")
        write_doc(superseding.root, DOC, front(decision="ADR-0001/1", allowed_paths=[NIST]), body())
        assert report(superseding).closing == []


class TestSweep:
    def test_files_that_mention_a_term_are_listed_with_their_line_counts_ignoring_case(self, repo):
        repo.write("legacy/a.md", "Kuma\nuptime-kuma\nother\n")
        repo.write("legacy/b.md", "KUMA\n")
        repo.commit("files that mention the term")
        found = {f.entry: f.why for f in report(repo, "kuma").sweep["kuma"]}
        assert found == {"legacy/a.md": "2 lines", "legacy/b.md": "1 line"}

    def test_decision_history_covered_files_and_the_project_doc_are_left_out(self, repo):
        revision(repo.root, "0001-x", 0, body="Kuma ran here.\n")
        repo.write("legacy/covered.md", "Kuma\n")
        repo.write("legacy/open.md", "Kuma\n")
        repo.commit("mentions in history, a covered file and an open one")
        write_doc(repo.root, DOC, front(allowed_paths=["legacy/covered.md"]), body())  # its own criterion names Kuma too
        assert entries(report(repo, "kuma").sweep["kuma"]) == ["legacy/open.md"]

    def test_each_term_gets_its_own_list(self, repo):
        repo.write("legacy/a.md", "kuma\n")
        repo.write("legacy/b.md", "gatus\n")
        repo.commit("one file per term")
        swept = report(repo, "kuma", "gatus").sweep
        assert {term: entries(found) for term, found in swept.items()} == {"kuma": ["legacy/a.md"], "gatus": ["legacy/b.md"]}

    def test_a_term_nothing_mentions_gives_an_empty_list(self, repo):
        assert report(repo, "zzz-nothing").sweep == {"zzz-nothing": []}

    def test_a_file_git_does_not_track_is_not_searched(self, repo):
        repo.write("legacy/untracked.md", "kuma\n")
        assert report(repo, "kuma").sweep["kuma"] == []

    def test_a_term_is_matched_as_text_not_as_a_pattern(self, repo):
        repo.write("legacy/a.md", "a.c and abc\n")
        repo.commit("a dot in the text")
        assert {f.entry: f.why for f in report(repo, "a.c").sweep["a.c"]} == {"legacy/a.md": "1 line"}

    def test_sweep_hits_are_not_added_to_the_proposed_entries(self, repo):
        repo.write("legacy/a.md", "kuma\n")
        repo.commit("a mention")
        assert "legacy/a.md" not in report(repo, "kuma").proposed()


class TestProposed:
    def test_keeps_todays_entries_then_adds_the_named_and_closing_ones_without_repeats(self, repo):
        repo.write("docs/topics/other.md", "See [the project](../projects/p.md) and [the topic](app.md).\n")
        repo.commit("a topic doc that links the project")
        write_doc(repo.root, DOC, front(allowed_paths=["docs/topics/app.md"]), body())
        assert report(repo).proposed() == ["docs/topics/app.md", "src/app/**", "docs/topics/other.md"]

    def test_an_entry_inside_another_new_entry_is_left_out(self, repo):
        # `src/app/` and `src/app/tasks.yaml` are both named; the directory glob covers the file
        assert [e for e in report(repo).proposed() if e.startswith("src/")] == ["src/app/**"]

    def test_a_doc_with_no_allowed_paths_starts_from_nothing(self, repo):
        assert report(repo).allowed == []
        assert report(repo).proposed() == ["src/app/**", "docs/topics/app.md"]


class TestCli:
    def test_prints_every_section_and_exits_zero_even_with_findings(self, repo):
        code, out = repo.run_cli("p", "--sweep", "kuma")
        assert code == 0, out
        for heading in ("Exempt without an entry", "Named by the project doc, not covered", "Edited by the closing PR, not covered", 'Mention "kuma"'):
            assert heading in out
        assert "- src/app/**" in out

    def test_a_clean_project_says_none_in_each_section(self, repo):
        write_doc(repo.root, DOC, front(allowed_paths=["src/app/**", "docs/topics/app.md"]), body())
        code, out = repo.run_cli("p")
        assert code == 0, out
        assert out.count("  none") == 3
        assert "- src/app/**" in out

    @pytest.mark.parametrize("arg", ["p", "p.md", "docs/projects/p.md"], ids=["name", "file-name", "path"])
    def test_names_the_project_doc_three_ways(self, repo, arg):
        code, out = repo.run_cli(arg)
        assert code == 0, out
        assert "PROJ-p (docs/projects/p.md)" in out

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (["missing"], "docs/projects/missing.md does not exist"),
            (["docs/topics/app.md"], "is not a project doc"),
            (["p", "--sweep", " "], "--sweep needs a non-empty term"),
        ],
        ids=["no-such-project", "not-a-project-doc", "blank-term"],
    )
    def test_refuses_what_it_cannot_read(self, repo, capsys, args, message):
        with pytest.raises(SystemExit) as stopped:
            cli.main([*args, "--root", str(repo.root)])
        assert stopped.value.code == 2
        assert message in capsys.readouterr().err
