"""Tests for check_accepted_records.py against a real temporary git repository:
the merge-base, the index and the commit trailers are exactly what mocks would
get wrong. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _doc_fixtures import GitRepo, revision
from doc_scripts import check_accepted_records as cli

LINEAGE = "0001-x"
PATH = f"docs/decisions/{LINEAGE}/revision-000.md"
BODY = "# 0001. Secret storage\n\n## Problem\n\nA problem.\n\n## Context\n\nHow it was found.\n\n## Decision\n\nRun a proxy.\n"


@pytest.fixture
def repo(root: Path) -> GitRepo:
    repo = GitRepo(root, cli)
    repo.git("init", "-q")
    repo.git("checkout", "-q", "-b", "main")
    revision(root, LINEAGE, 0, status="accepted", body=BODY)
    revision(root, "0002-y", 0, status="working", body=BODY)
    repo.commit("base")
    return repo


def edit(repo: GitRepo, old: str, new: str, rel: str = PATH) -> None:
    path = repo.root / rel
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


class TestFrozenSections:
    def test_cutting_context_passes(self, repo):
        repo.branch()
        edit(repo, "How it was found.", "Shorter.")
        repo.commit("condense")
        code, out = repo.pr()
        assert code == 0, out

    def test_changing_the_decision_fails(self, repo):
        repo.branch()
        edit(repo, "Run a proxy.", "Run two proxies.")
        repo.commit("quietly change")
        code, out = repo.pr()
        assert code == 1, out
        assert PATH in out
        assert "## Decision" in out

    def test_a_trailer_on_any_commit_of_the_change_excuses_the_path(self, repo):
        repo.branch()
        edit(repo, "Run a proxy.", "Run a proxy (fixed typo).")
        repo.commit(f"fix a typo\n\nEditorial-Fix: {PATH}")
        code, out = repo.pr()
        assert code == 0, out

    def test_a_trailer_for_another_path_does_not(self, repo):
        repo.branch()
        edit(repo, "Run a proxy.", "Run two proxies.")
        repo.commit("fix\n\nEditorial-Fix: docs/decisions/0002-y/revision-000.md")
        code, _ = repo.pr()
        assert code == 1

    def test_a_working_revision_may_change_freely(self, repo):
        repo.branch()
        edit(repo, "Run a proxy.", "Run two proxies.", "docs/decisions/0002-y/revision-000.md")
        repo.commit("rework")
        code, out = repo.pr()
        assert code == 0, out

    def test_a_branch_behind_main_is_not_blamed_for_mains_edits(self, repo):
        repo.branch()
        (repo.root / "notes.txt").write_text("x\n", encoding="utf-8")
        repo.commit("unrelated")
        repo.git("checkout", "-q", "main")
        edit(repo, "Run a proxy.", "Run a proxy (fixed upstream).")
        repo.commit("main edits the record")
        code, out = repo.pr()
        assert code == 0, out

    def test_staged_mode_warns_and_passes(self, repo):
        edit(repo, "Run a proxy.", "Run two proxies.")
        repo.git("add", "-A")
        code, out = repo.run_cli("--staged")
        assert code == 0, out
        assert "::warning::" in out
        assert "## Decision" in out


class TestRemovedLineages:
    def delete(self, repo, lineage=LINEAGE):
        repo.branch()
        repo.git("rm", "-q", "-r", f"docs/decisions/{lineage}")

    def test_deleting_an_accepted_lineage_with_no_record_fails(self, repo):
        self.delete(repo)
        repo.commit("remove")
        code, out = repo.pr()
        assert code == 1, out
        assert "ADR 0001" in out

    def test_a_ledger_row_in_the_same_change_accounts_for_it(self, repo):
        self.delete(repo)
        repo.write("docs/decisions/removed.md", "# Removed\n\n| ADR | Fate | Where it went |\n| :--- | :--- | :--- |\n| 0001 | demoted | a topic doc |\n")
        repo.commit("remove and record")
        code, out = repo.pr()
        assert code == 0, out

    def test_merging_into_a_lineage_that_lists_the_former_id_accounts_for_it(self, repo):
        self.delete(repo)
        revision(repo.root, "0003-merged", 0, status="accepted", former_ids=["ADR-0001"], body=BODY)
        repo.commit("merge")
        code, out = repo.pr()
        assert code == 0, out

    def test_deleting_a_lineage_that_only_held_a_working_revision_passes(self, repo):
        self.delete(repo, "0002-y")
        repo.commit("drop the draft")
        code, out = repo.pr()
        assert code == 0, out

    def test_staged_mode_fails_on_an_unaccounted_removal(self, repo):
        repo.git("rm", "-q", "-r", f"docs/decisions/{LINEAGE}")
        code, out = repo.run_cli("--staged")
        assert code == 1, out
