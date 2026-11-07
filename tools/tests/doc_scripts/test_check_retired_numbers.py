"""Tests for doc_retired.py and check_retired_numbers.py, run against throwaway
git repositories. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _doc_fixtures import assert_one_error, revision
from doc_scripts import check_retired_numbers as cli
from doc_scripts import doc_retired as retired

LEDGER = "# Removed\n\n| ADR | Fate | Where it went |\n| :--- | :--- | :--- |\n| 0032 | demoted | the tooling topic doc |\n"
LINK_TARGET = "../0111-merged/revision-000.md"


class Tree:
    """A tree in which 0111 absorbed 0017 and 0019, and 0032 was demoted."""

    def __init__(self, root: Path) -> None:
        self.root = root
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
        revision(root, "0111-merged", 0, status="accepted", former_ids=["ADR-0017", "ADR-0019"])
        self.write("docs/decisions/removed.md", LEDGER)

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def errors(self) -> list[str]:
        return retired.retired_reference_errors(self.root)


@pytest.fixture
def tree(root: Path) -> Tree:
    return Tree(root)


class TestRetiredNumbers:
    def test_a_former_id_maps_to_the_lineage_that_took_it(self, tree):
        assert retired.retired_numbers(tree.root)["0017"] == ("merged into ADR 0111", "0111")

    def test_a_ledger_number_has_no_replacement(self, tree):
        assert retired.retired_numbers(tree.root)["0032"] == ("demoted (the tooling topic doc)", None)

    def test_a_number_a_lineage_holds_is_never_retired(self, tree):
        revision(tree.root, "0017-back", 0)
        assert "0017" not in retired.retired_numbers(tree.root)


class TestProse:
    def test_a_space_form_reference_is_reported_with_its_line_and_the_new_number(self, tree):
        tree.write("docs/topics/a.md", "one\nsee ADR 0017 here\n")
        assert_one_error(tree.errors(), "docs/topics/a.md:2:", "ADR 0017", "merged into ADR 0111", "name ADR 0111")

    def test_a_hyphen_form_in_a_code_comment_is_reported(self, tree):
        tree.write("ansible/roles/x/tasks/main.yaml", "# the scope ADR-0019 sets\n")
        assert_one_error(tree.errors(), "main.yaml:1:", "ADR 0019")

    def test_every_number_of_a_list_after_adrs_is_checked(self, tree):
        tree.write("docs/topics/a.md", "ADRs 0111, 0017 and 0019 agree\n")
        assert [e.split(": ")[1].split(";")[0] for e in tree.errors()] == [
            "names ADR 0017, which was merged into ADR 0111",
            "names ADR 0019, which was merged into ADR 0111",
        ]

    def test_both_ends_of_a_range_are_checked(self, tree):
        tree.write("docs/topics/a.md", "ADRs 0017 through 0032\n")
        assert len(tree.errors()) == 2

    @pytest.mark.parametrize("dash", ["-", "\u2013"])
    def test_a_dashed_range_is_checked(self, tree, dash):
        tree.write("docs/topics/a.md", f"ADRs 0111{dash}0019\n")
        assert_one_error(tree.errors(), "ADR 0019")

    def test_a_reference_to_a_ledger_number_says_where_it_went(self, tree):
        tree.write("docs/topics/a.md", "ADR 0032 explains it\n")
        assert_one_error(tree.errors(), "ADR 0032", "demoted (the tooling topic doc)", "drop the mention")

    def test_a_live_number_is_clean(self, tree):
        tree.write("docs/topics/a.md", "ADR 0111 and ADR-0111\n")
        assert tree.errors() == []

    def test_a_bare_number_without_adr_is_not_a_reference(self, tree):
        revision(tree.root, "0037-x", 0, body="# T\n\nreplaced in part (0017 by 0111, 0019 by 0111)\n", status="accepted")
        assert tree.errors() == []

    def test_correcting_the_reference_clears_the_error(self, tree):
        tree.write("docs/topics/a.md", "ADR 0017\n")
        assert tree.errors()
        tree.write("docs/topics/a.md", "ADR 0111\n")
        assert tree.errors() == []


class TestLinks:
    def test_a_bare_number_over_a_link_to_another_number_is_reported(self, tree):
        tree.write("docs/topics/a.md", f"[0017]({LINK_TARGET})\n")
        assert_one_error(tree.errors(), "link text names ADR 0017", "link goes to ADR 0111")

    def test_a_named_link_is_reported_once_as_the_link(self, tree):
        tree.write("docs/topics/a.md", f"[ADR 0017 (Short name)]({LINK_TARGET})\n")
        assert_one_error(tree.errors(), "link text names ADR 0017")

    def test_a_link_split_over_two_lines_is_found_on_the_line_of_its_number(self, tree):
        tree.write("docs/topics/a.md", f"[ADR\n0017 (Short name)]({LINK_TARGET}#anchor)\n")
        assert_one_error(tree.errors(), "a.md:2:")

    def test_a_link_whose_text_matches_its_target_is_clean(self, tree):
        tree.write("docs/topics/a.md", f"[0111]({LINK_TARGET}) and [ADR 0111 (Short name)]({LINK_TARGET})\n")
        assert tree.errors() == []


class TestWhatIsNotAReference:
    def test_the_ledger_is_not_read(self, tree):
        tree.write("docs/decisions/removed.md", LEDGER + "| 0033 | dropped | folded into ADR 0032 |\n")
        assert tree.errors() == []

    def test_an_inline_former_ids_field_is_not_read(self, tree):
        revision(tree.root, "0112-other", 0, former_ids=["ADR-0017"])
        assert tree.errors() == []

    def test_a_block_former_ids_field_is_not_read_but_the_next_field_is(self, tree):
        tree.write("docs/x.md", "former_ids:\n  - ADR-0017\n  - ADR-0019\nrelated: ADR-0017\n")
        assert_one_error(tree.errors(), "x.md:4:")

    def test_the_formerly_text_of_a_generated_index_is_not_read(self, tree):
        tree.write("docs/decisions/README.md", "| Accepted | Formerly ADR-0017, ADR-0019 |\n")
        assert tree.errors() == []

    def test_the_doc_tooling_tests_are_not_read(self, tree):
        tree.write("tools/tests/doc_scripts/test_x.py", "# ADR 0017\n")
        assert tree.errors() == []

    def test_other_tests_are_read(self, tree):
        tree.write("tools/tests/cd_agent/test_x.py", "# ADR 0017\n")
        assert_one_error(tree.errors(), "tools/tests/cd_agent/test_x.py:1:")

    def test_a_hyphen_id_in_a_markdown_fence_is_an_example(self, tree):
        tree.write("docs/x.md", "```yaml\nid: ADR-0017\n```\n")
        assert tree.errors() == []

    def test_a_space_form_in_a_markdown_fence_is_still_a_reference(self, tree):
        tree.write("docs/x.md", "```yaml\n# see ADR 0017\n```\n")
        assert_one_error(tree.errors(), "x.md:2:")

    def test_a_hyphen_id_in_a_code_file_is_not_a_fence(self, tree):
        tree.write("tools/x.py", '"""\n```\nid: ADR-0017\n```\n"""\n')
        assert_one_error(tree.errors(), "x.py:3:")

    def test_a_binary_file_is_skipped(self, tree):
        (tree.root / "logo.png").write_bytes(b"\x89PNG\xff\xfe ADR 0017")
        assert tree.errors() == []

    def test_a_file_git_ignores_is_skipped(self, tree):
        tree.write(".gitignore", "scratch.md\n")
        tree.write("scratch.md", "ADR 0017\n")
        assert tree.errors() == []


class TestFrozenSections:
    TRAILER = "`Editorial-Fix: docs/decisions/0050-x/revision-000.md`"

    def accepted(self, tree: Tree, body: str, status: str = "accepted", **fm) -> None:
        revision(tree.root, "0050-x", 0, body=body, status=status, **fm)

    @pytest.mark.parametrize("section", ["Problem", "Decision", "Invariants", "Non-goals", "Reconsideration triggers"])
    def test_a_frozen_section_of_an_accepted_revision_names_the_trailer(self, tree, section):
        self.accepted(tree, f"# T\n\n## {section}\n\nSee ADR 0017.\n\n## Consequences\n\nfine\n")
        assert_one_error(tree.errors(), "frozen section", self.TRAILER)

    def test_a_superseded_revision_is_held_too(self, tree):
        self.accepted(tree, "# T\n\n## Decision\n\nSee ADR 0017.\n", status="superseded", superseded_by=1)
        assert_one_error(tree.errors(), "frozen section")

    def test_the_title_and_solution_are_frozen(self, tree):
        self.accepted(tree, "# T\n", solution="Supersedes ADR 0017")
        assert_one_error(tree.errors(), "frozen section")

    def test_a_section_that_may_be_cut_needs_no_trailer(self, tree):
        self.accepted(tree, "# T\n\n## Decision\n\nfine\n\n## Context\n\nSee ADR 0017.\n")
        errors = tree.errors()
        assert_one_error(errors, "0050-x/revision-000.md:")
        assert "Editorial-Fix" not in errors[0]

    def test_a_working_revision_needs_no_trailer(self, tree):
        self.accepted(tree, "# T\n\n## Decision\n\nSee ADR 0017.\n", status="working")
        errors = tree.errors()
        assert len(errors) == 1
        assert "Editorial-Fix" not in errors[0]

    def test_a_topic_doc_with_a_decision_heading_needs_no_trailer(self, tree):
        tree.write("docs/topics/a.md", "## Decision\n\nSee ADR 0017.\n")
        assert "Editorial-Fix" not in tree.errors()[0]


class TestCli:
    def test_a_clean_tree_exits_zero(self, tree, capsys):
        assert cli.main(["--root", str(tree.root)]) == 0
        assert "No file names" in capsys.readouterr().out

    def test_a_reference_exits_one_and_prints_an_annotation(self, tree, capsys):
        tree.write("docs/topics/a.md", "ADR 0017\n")
        assert cli.main(["--root", str(tree.root)]) == 1
        captured = capsys.readouterr()
        assert captured.out.startswith("::error::docs/topics/a.md:1:")
        assert "1 reference(s)" in captured.err
