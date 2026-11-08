"""Tests for merge_adr_links.py, run against throwaway git repositories.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from _doc_fixtures import project, revision
from doc_scripts import doc_retired
from doc_scripts import merge_adr_links as merge

A, B, NEW = "0017-first", "0018-second", "0111-merged"
DECISION = "# T\n\n## Decision\n\n{text}\n\n## Context\n\n{context}\n"
LINK_A = "../0017-first/revision-000.md"
LINK_NEW = "../0111-merged/revision-000.md"


class Tree:
    """0017 and 0018 are sources, 0111 the new lineage that lists both; 0050 is another record."""

    def __init__(self, root: Path) -> None:
        self.root = root
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
        revision(root, A, 0, status="accepted")
        revision(root, B, 0, status="accepted")
        revision(root, NEW, 0, status="accepted", short="Merged short", former_ids=["ADR-0017", "ADR-0018"])

    def other(self, text: str = "Plain.", context: str = "Plain.", status: str = "accepted", **fm) -> Path:
        return revision(self.root, "0050-other", 0, body=DECISION.format(text=text, context=context), status=status, **fm)

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def plan(self, sources: tuple[str, ...] = ("0017", "0018")) -> merge.Plan:
        return merge.plan_merge(self.root, "0111", list(sources))

    def run(self, sources: tuple[str, ...] = ("0017", "0018")) -> merge.Plan:
        plan = self.plan(sources)
        merge.apply_plan(self.root, plan)
        return plan


@pytest.fixture
def tree(root: Path) -> Tree:
    return Tree(root)


OTHER = "docs/decisions/0050-other/revision-000.md"


class TestLinks:
    @pytest.mark.parametrize("name", ["revision-000.md", "revision-001.md", "revision-000-c.md"])
    def test_a_link_to_any_revision_of_a_source_goes_to_the_new_revision_zero(self, tree, name):
        tree.write("docs/topics/a.md", f"[x](../decisions/{A}/{name}#anchor)\n")
        tree.run()
        assert tree.read("docs/topics/a.md") == f"[x](../decisions/{NEW}/revision-000.md#anchor)\n"

    def test_a_named_link_takes_the_new_number_and_short_name(self, tree):
        tree.write("docs/topics/a.md", f"[ADR 0017 (Old short)]({LINK_A}) and [ADR 0018 revision 1 (Other)]({LINK_A.replace('0017-first', B)})\n")
        tree.run()
        assert tree.read("docs/topics/a.md") == f"[ADR 0111 (Merged short)]({LINK_NEW}) and [ADR 0111 revision 1 (Merged short)]({LINK_NEW})\n"

    def test_a_bare_number_link_takes_the_new_number(self, tree):
        tree.write("docs/topics/a.md", f"[0017]({LINK_A})\n")
        tree.run()
        assert tree.read("docs/topics/a.md") == f"[0111]({LINK_NEW})\n"

    def test_a_link_to_the_new_lineage_keeps_a_correct_short_name(self, tree):
        tree.write("docs/topics/a.md", f"[ADR 0111 (Merged short)]({LINK_NEW})\n")
        assert tree.plan().edits == {}

    def test_a_link_to_another_record_is_left_alone(self, tree):
        tree.write("docs/topics/a.md", "[ADR 0050 (Other)](../decisions/0050-other/revision-000.md)\n")
        assert tree.plan().edits == {}


class TestProse:
    def test_prose_and_code_comments_name_the_new_number(self, tree):
        tree.write("docs/topics/a.md", "See ADR 0017.\n")
        tree.write("ansible/roles/x/tasks/main.yaml", "# the scope in ADR-0018\n")
        tree.run()
        assert tree.read("docs/topics/a.md") == "See ADR 0111.\n"
        assert tree.read("ansible/roles/x/tasks/main.yaml") == "# the scope in ADR-0111\n"

    def test_a_list_is_rewritten_and_flagged_for_review(self, tree):
        tree.write("docs/topics/a.md", "ADRs 0017 and 0018 agree\n")
        plan = tree.run()
        assert tree.read("docs/topics/a.md") == "ADRs 0111 and 0111 agree\n"
        assert plan.review == ["docs/topics/a.md:1: 0017 was in a list or range", "docs/topics/a.md:1: 0018 was in a list or range"]

    @pytest.mark.parametrize(
        "text",
        [
            f"see ADRs\n[0017]({LINK_A}) through\n[0026](../0026-x/revision-000.md) here",
            f"from [0050](../0050-other/revision-000.md) through [0017]({LINK_A})",
            f"ADRs [ADR 0017 (x)]({LINK_A}) and [ADR 0050 (y)](../0050-other/revision-000.md)",
            "ADR 0017 through ADR 0026",
        ],
        ids=["link-range", "range-end", "link-list", "prose-range"],
    )
    def test_a_range_or_list_of_links_is_flagged_for_review(self, tree, text):
        tree.write("docs/topics/a.md", text + "\n")
        assert len(tree.plan().review) == 1

    def test_a_single_reference_needs_no_review(self, tree):
        tree.write("docs/topics/a.md", f"ADR 0017, [0017]({LINK_A}) and [ADR 0017 (x)]({LINK_A})'s\n")
        assert tree.plan().review == []

    def test_a_file_that_names_no_source_is_untouched(self, tree):
        tree.write("docs/topics/a.md", "ADR 0050 and ADR 0111.\n")
        assert tree.plan().edits == {}


class TestFrontmatter:
    def test_related_names_the_new_lineage_once_and_keeps_the_others(self, tree):
        tree.other(related=["ADR-0017", "ADR-0060", "ADR-0018"])
        tree.run()
        assert "related: [ADR-0111, ADR-0060]\n" in tree.read(OTHER)

    def test_a_block_list_is_read_too(self, tree):
        tree.other(related=["ADR-0017"])
        assert "related:\n- ADR-0017" in tree.read(OTHER)
        tree.run()
        assert "related: [ADR-0111]\n" in tree.read(OTHER)

    def test_narrows_names_the_new_lineage(self, tree):
        tree.other(narrows="ADR-0017")
        tree.run()
        assert "narrows: ADR-0111\n" in tree.read(OTHER)

    def test_a_related_list_that_names_no_source_is_not_reformatted(self, tree):
        tree.other(related=["ADR-0060", "ADR-0061"])
        before = tree.read(OTHER)
        tree.run()
        assert tree.read(OTHER) == before

    def test_a_project_decision_names_revision_zero_of_the_new_lineage(self, tree):
        project(tree.root, "p", decision="ADR-0017/1", also_implements=["ADR-0018/0"])
        tree.run()
        text = tree.read("docs/projects/p.md")
        assert "decision: ADR-0111/0\n" in text
        assert "also_implements:\n- ADR-0111/0\n" in text


class TestWhatTheReportMustSay:
    def test_a_change_to_a_frozen_section_of_an_accepted_record_needs_a_trailer(self, tree):
        tree.other(text=f"See ADR 0017 and [ADR 0017 (x)]({LINK_A}).")
        plan = tree.run()
        assert plan.frozen == [OTHER]
        assert f"Editorial-Fix: {OTHER}" in merge.report(plan)

    def test_a_change_to_a_section_that_may_be_cut_needs_none(self, tree):
        tree.other(context="See ADR 0017.")
        assert tree.plan().frozen == []

    def test_a_link_target_alone_is_not_a_frozen_change(self, tree):
        tree.other(text=f"See [ADR 0111 (Merged short)]({LINK_A}).")
        plan = tree.plan()
        assert OTHER in plan.edits
        assert plan.frozen == []

    def test_a_revision_that_is_not_accepted_needs_none(self, tree):
        tree.other(text="See ADR 0017.", status="working")
        assert tree.plan().frozen == []

    def test_a_related_edit_is_not_a_frozen_change(self, tree):
        tree.other(related=["ADR-0017"])
        plan = tree.plan()
        assert OTHER in plan.edits
        assert plan.frozen == []

    def test_a_project_whose_frontmatter_changes_is_worked(self, tree):
        project(tree.root, "p", decision="ADR-0017/0")
        assert tree.plan().worked_projects == ["docs/projects/p.md"]

    def test_a_project_whose_prose_changes_is_not_worked(self, tree):
        project(tree.root, "p")
        tree.write("docs/projects/p.md", tree.read("docs/projects/p.md") + "\nSee ADR 0017.\n")
        plan = tree.plan()
        assert "docs/projects/p.md" in plan.edits
        assert plan.worked_projects == []

    def test_nothing_to_do_says_so(self, tree):
        plan = tree.plan()
        assert plan.edits == {} and plan.frozen == []
        assert merge.report(plan).startswith("Rewrote 0 file(s)")


class TestWhatIsNotEdited:
    def test_the_sources_are_not_edited(self, tree):
        revision(tree.root, A, 1, body="# T\n\nADR 0017 and ADR 0018\n", status="accepted", supersedes=0)
        assert tree.plan().edits == {}

    def test_the_generated_views_are_not_edited(self, tree):
        tree.write("docs/decision-index.md", f"| [0017](decisions/{A}/revision-000.md) | ADR 0017 |\n")
        tree.write("docs/project-planning.md", "ADR 0017\n")
        assert tree.plan().edits == {}

    def test_the_new_lineage_is_not_edited_but_what_it_names_is_reported(self, tree):
        revision(
            tree.root,
            NEW,
            0,
            body="# T\n\nSee ADR 0017 and docs/decisions/0018-second/.\n",
            status="accepted",
            short="Merged short",
            former_ids=["ADR-0017", "ADR-0018"],
        )
        plan = tree.plan()
        assert plan.edits == {}
        assert any("revision-000.md:" in item and "ADR 0017" in item for item in plan.left)
        assert any("names the source directory 0018-second" in item for item in plan.left)

    def test_the_former_ids_of_the_new_lineage_are_not_a_reference(self, tree):
        assert tree.plan().left == []

    def test_a_directory_reference_to_a_source_is_left_for_a_person(self, tree):
        tree.write("docs/topics/a.md", "In docs/decisions/0017-first/ there is the record.\n")
        plan = tree.plan()
        assert plan.edits == {}
        assert plan.left == ["docs/topics/a.md: still names the source directory 0017-first"]

    def test_a_source_the_command_was_not_given_is_left_alone(self, tree):
        tree.write("docs/topics/a.md", "ADR 0017 and ADR 0018\n")
        tree.plan(("0017",))
        revision(tree.root, "0111-merged", 0, status="accepted", short="Merged short", former_ids=["ADR-0017"])
        merge.apply_plan(tree.root, tree.plan(("0017",)))
        assert tree.read("docs/topics/a.md") == "ADR 0111 and ADR 0018\n"


class TestWhole:
    def test_once_the_sources_are_deleted_the_retired_number_check_is_clean(self, tree):
        tree.write("docs/topics/a.md", f"See ADR 0017, [0018]({LINK_A.replace('0017-first', B)}) and ADR-0018.\n")
        tree.other(text=f"[ADR 0017 (x)]({LINK_A})", related=["ADR-0017", "ADR-0018"])
        assert doc_retired.retired_reference_errors(tree.root) == []  # sources still live: nothing is retired yet
        tree.run()
        for d in (A, B):
            shutil.rmtree(tree.root / "docs/decisions" / d)
        assert doc_retired.retired_reference_errors(tree.root) == []

    def test_control_without_the_rewrite_the_check_fails_once_the_sources_are_gone(self, tree):
        tree.write("docs/topics/a.md", "See ADR 0017.\n")
        for d in (A, B):
            shutil.rmtree(tree.root / "docs/decisions" / d)
        assert len(doc_retired.retired_reference_errors(tree.root)) == 1

    def test_a_second_run_changes_nothing(self, tree):
        tree.write("docs/topics/a.md", f"ADRs 0017 and 0018, [ADR 0017 (x)]({LINK_A})\n")
        tree.other(related=["ADR-0017"], text="ADR 0018")
        tree.run()
        assert tree.plan().edits == {}


class TestValidation:
    def test_the_new_lineage_must_list_every_source(self, tree):
        revision(tree.root, NEW, 0, status="accepted", short="Merged short", former_ids=["ADR-0017"])
        with pytest.raises(ValueError, match="must list ADR-0018 in `former_ids`"):
            tree.plan()

    def test_an_unknown_lineage_is_reported(self, tree):
        with pytest.raises(ValueError, match="no decision lineage matches '0999'"):
            tree.plan(("0017", "0999"))

    def test_the_new_lineage_cannot_be_its_own_source(self, tree):
        with pytest.raises(ValueError, match="both the new lineage and a source"):
            tree.plan(("0111",))

    def test_a_directory_name_is_accepted(self, tree):
        tree.write("docs/topics/a.md", "ADR 0017\n")
        merge.plan_merge(tree.root, NEW, [A, B])

    def test_a_directory_name_with_the_wrong_slug_is_not(self, tree):
        with pytest.raises(ValueError, match="no decision lineage matches"):
            merge.plan_merge(tree.root, NEW, ["0017-wrong"])


class TestCli:
    def test_dry_run_writes_nothing(self, tree, capsys):
        tree.write("docs/topics/a.md", "ADR 0017\n")
        assert merge.main(["0111", "0017", "0018", "--dry-run", "--root", str(tree.root)]) == 0
        assert tree.read("docs/topics/a.md") == "ADR 0017\n"
        assert "Would rewrite 1 file(s)" in capsys.readouterr().out

    def test_a_run_writes_and_reports(self, tree, capsys):
        tree.write("docs/topics/a.md", "ADR 0017\n")
        assert merge.main(["0111", "0017", "0018", "--root", str(tree.root)]) == 0
        assert tree.read("docs/topics/a.md") == "ADR 0111\n"
        out = capsys.readouterr().out
        assert "Rewrote 1 file(s)" in out
        assert "Still to do: delete the source directories" in out

    def test_an_error_exits_two_and_writes_nothing(self, tree, capsys):
        tree.write("docs/topics/a.md", "ADR 0017\n")
        assert merge.main(["0111", "0999", "--root", str(tree.root)]) == 2
        assert "error: no decision lineage matches '0999'" in capsys.readouterr().err
        assert tree.read("docs/topics/a.md") == "ADR 0017\n"
