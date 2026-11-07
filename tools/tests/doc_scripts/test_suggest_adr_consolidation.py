"""Tests for suggest_adr_consolidation.py: each signal on a throwaway tree.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from _doc_fixtures import project, revision
from doc_scripts import suggest_adr_consolidation as tool
from doc_scripts.doc_frontmatter import load_lineages


def body(problem="A problem.", decision="A decision."):
    return f"# 0001. T\n\n## Problem\n\n{problem}\n\n## Decision\n\n{decision}\n"


def files(n):
    return " ".join(f"`tools/file{i}.py`" for i in range(n))


class TestImplementationDetail:
    def test_an_accepted_decision_naming_many_files_is_reported(self, root):
        revision(root, "0032-moves", 0, status="accepted", body=body(decision=files(tool.FILE_REFERENCE_LIMIT)))
        revision(root, "0033-small", 0, status="accepted", body=body(decision=files(tool.FILE_REFERENCE_LIMIT - 1)))
        assert tool.implementation_detail(load_lineages(root)) == [("ADR-0032", tool.FILE_REFERENCE_LIMIT)]

    def test_a_working_decision_is_not_reported(self, root):
        revision(root, "0032-moves", 0, status="working", body=body(decision=files(20)))
        assert tool.implementation_detail(load_lineages(root)) == []

    def test_a_file_named_twice_counts_once(self, root):
        revision(root, "0032-moves", 0, status="accepted", body=body(decision="`a.py` " * 30))
        assert tool.implementation_detail(load_lineages(root)) == []


class TestSimilarProblems:
    def test_the_same_problem_for_two_cases_is_reported(self, root):
        text = "Pinned artifacts installed on hosts are trusted without showing the digest came from the publisher"
        revision(root, "0077-a", 0, title="A", short="a", summary="x", body=body(problem=text + " release"))
        revision(root, "0084-b", 0, title="B", short="b", summary="y", body=body(problem=text + " image"))
        revision(root, "0090-c", 0, title="C", short="c", summary="z", body=body(problem="Licences of adopted software are unknown"))
        [(a, b, score)] = tool.similar_problems(load_lineages(root))
        assert (a, b) == ("ADR-0077", "ADR-0084")
        assert score >= tool.SIMILARITY_LIMIT

    def test_unrelated_problems_are_not(self, root):
        revision(root, "0001-a", 0, title="A", short="a", summary="x", body=body(problem="Containers reach the docker socket directly"))
        revision(root, "0002-b", 0, title="B", short="b", summary="y", body=body(problem="Licences of adopted software are unknown"))
        assert tool.similar_problems(load_lineages(root)) == []

    def test_an_old_record_without_a_problem_section_is_matched_on_its_title_and_summary(self, root):
        title = "Pinned artifact provenance checking"
        summary = "Shows that a pinned digest came from the publisher"
        revision(root, "0077-a", 0, title=title, short="a", summary=summary, body="# 0077. A\n\n## Decision\n\nx\n")
        revision(root, "0084-b", 0, title=title + " again", short="b", summary=summary, body="# 0084. B\n\n## Decision\n\ny\n")
        [(a, b, _)] = tool.similar_problems(load_lineages(root))
        assert (a, b) == ("ADR-0077", "ADR-0084")


class TestClusters:
    def lineage(self, root, number, related, topic="secrets-store"):
        revision(root, f"{number}-x", 0, title=number, short=number, topic=topic, related=related)

    def test_three_mutually_related_lineages_of_one_topic_are_a_cluster(self, root):
        self.lineage(root, "0014", ["ADR-0024", "ADR-0025"])
        self.lineage(root, "0024", ["ADR-0014", "ADR-0025"])
        self.lineage(root, "0025", ["ADR-0014", "ADR-0024"])
        assert tool.tight_clusters(load_lineages(root)) == [["ADR-0014", "ADR-0024", "ADR-0025"]]

    def test_one_way_links_do_not_make_a_cluster(self, root):
        self.lineage(root, "0014", ["ADR-0024", "ADR-0025"])
        self.lineage(root, "0024", [])
        self.lineage(root, "0025", [])
        assert tool.tight_clusters(load_lineages(root)) == []

    def test_a_pair_is_too_small_and_other_topics_do_not_join(self, root):
        self.lineage(root, "0014", ["ADR-0024"])
        self.lineage(root, "0024", ["ADR-0014"])
        self.lineage(root, "0025", ["ADR-0014"], topic="deployment-platform")
        assert tool.tight_clusters(load_lineages(root)) == []


class TestReport:
    def test_without_the_flag_there_is_no_quarterly_section(self, root):
        revision(root, "0001-a", 0)
        out = tool.render(root, report=False)
        assert "# Decision records worth a look" in out
        assert "Quarterly report" not in out

    def test_the_report_flags_too_many_active_projects(self, root):
        from doc_scripts import generate_doc_indexes as gen

        for i in range(gen.ACTIVE_PROJECT_LIMIT + 1):
            project(root, f"p{i}", status="building")
        assert "over the limit" in tool.render(root, report=True)


SAME = "Pinned artifacts installed on hosts are trusted without showing the digest came from the publisher"


def readme(root, *rows, header="| Records | Why they stay separate | Status when read |"):
    path = root / "docs/decisions/README.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    table = "\n".join([header, "| :--- | :--- | :--- |", *rows])
    path.write_text(
        f"# Decisions\n\n### {tool.KEPT_HEADING}\n\nIntro.\n\n{table}\n\nNothing is renumbered.\n\n## Next\n\n| ADR 0077 and 0084 | x | 0077 working |\n",
        encoding="utf-8",
    )


def similar_pair(root, status_a="accepted", status_b="accepted"):
    revision(root, "0077-a", 0, title="A", short="a", summary="x", status=status_a, body=body(problem=SAME + " release"))
    revision(root, "0084-b", 0, title="B", short="b", summary="y", status=status_b, body=body(problem=SAME + " image"))


def report(root):
    return tool.render(root, report=False)


class TestKeptApart:
    def test_a_pair_with_a_recorded_reason_and_unchanged_statuses_is_left_out(self, root):
        similar_pair(root)
        readme(root, "| ADR 0077 and 0084 | Different artifacts. | 0077 accepted, 0084 accepted |")
        out = report(root)
        assert "ADR-0077 and ADR-0084" not in out
        assert "## Similar problems (one problem stated for different cases? merge)\n- none" in out
        assert "to read again (a record changed status or is gone)\n- none" in out

    def test_control_without_the_row_the_pair_is_listed(self, root):
        similar_pair(root)
        assert "- ADR-0077 and ADR-0084:" in report(root)

    def test_a_status_change_lists_the_row_to_read_again_with_its_reason(self, root):
        similar_pair(root, status_a="abandoned")
        readme(root, "| ADR 0077 and 0084 | Different artifacts. | 0077 accepted, 0084 accepted |")
        out = report(root)
        assert "- ADR 0077 and 0084: ADR-0077 was accepted, now abandoned. Kept apart because: Different artifacts." in out
        assert "- ADR-0077 and ADR-0084:" not in out

    def test_a_working_revision_added_to_an_accepted_record_counts_as_a_change(self, root):
        similar_pair(root)
        revision(root, "0077-a", 1, title="A", short="a", summary="x", status="working", supersedes=0, body=body(problem=SAME))
        readme(root, "| ADR 0077 and 0084 | Different artifacts. | 0077 accepted, 0084 accepted |")
        assert "ADR-0077 was accepted, now working" in report(root)

    def test_a_record_that_is_gone_lists_the_row(self, root):
        revision(root, "0077-a", 0)
        readme(root, "| ADR 0077 and 0084 | Different artifacts. | 0077 working, 0084 accepted |")
        assert "ADR-0084 is no longer a record" in report(root)

    def test_a_row_with_no_status_is_listed_not_trusted(self, root):
        similar_pair(root)
        readme(root, "| ADR 0077 and 0084 | Different artifacts. | 0077 accepted |")
        out = report(root)
        assert "no status is recorded for ADR-0084" in out
        assert "- ADR-0077 and ADR-0084:" not in out

    def test_a_table_without_the_status_column_lists_every_row(self, root):
        similar_pair(root)
        readme(root, "| ADR 0077 and 0084 | Different artifacts. |", header="| Records | Why they stay separate |")
        assert "no status is recorded for ADR-0077; no status is recorded for ADR-0084" in report(root)

    def test_a_row_that_names_no_pair_is_reported_unread(self, root):
        similar_pair(root)
        readme(root, "| Everything else | Fine. | 0077 accepted |")
        out = report(root)
        assert "row not understood: | Everything else | Fine. | 0077 accepted |" in out
        assert "- ADR-0077 and ADR-0084:" in out

    def test_a_status_change_in_an_unrelated_record_of_the_row_leaves_the_candidate_out_and_lists_the_row(self, root):
        similar_pair(root)
        revision(root, "0090-c", 0, title="C", short="c", summary="z", status="approved", body=body(problem="Licences of adopted software are unknown"))
        readme(root, "| ADR 0077, 0084, 0090 | Three boundaries. | 0077 accepted, 0084 accepted, 0090 working |")
        out = report(root)
        assert "- ADR-0077 and ADR-0084:" not in out
        assert "ADR-0090 was working, now approved" in out

    def test_a_cluster_inside_a_recorded_group_is_left_out(self, root):
        for number in ("0014", "0024", "0025"):
            others = [f"ADR-{n}" for n in ("0014", "0024", "0025") if n != number]
            revision(root, f"{number}-x", 0, title=number, short=number, topic="secrets-store", related=others, status="accepted")
        assert "- ADR-0014, ADR-0024, ADR-0025" in report(root)
        readme(root, "| ADR 0014, 0024, 0025 | One topic, three choices. | 0014 accepted, 0024 accepted, 0025 accepted |")
        assert "ADR-0014, ADR-0024, ADR-0025" not in report(root)

    def test_a_row_may_name_several_groups(self, root):
        similar_pair(root)
        readme(root, "| ADR 0001 and 0002; 0077 and 0084 | Different. | 0001 accepted, 0002 accepted, 0077 accepted, 0084 accepted |")
        revision(root, "0001-p", 0, status="accepted")
        revision(root, "0002-q", 0, status="accepted")
        assert "- ADR-0077 and ADR-0084:" not in report(root)

    def test_a_pair_only_part_of_a_row_covers_is_still_listed(self, root):
        similar_pair(root)
        readme(root, "| ADR 0077 and 0090; 0084 and 0090 | Different. | 0077 accepted, 0084 accepted, 0090 accepted |")
        revision(root, "0090-c", 0, status="accepted", title="C", short="c", summary="z", body=body(problem="Licences of adopted software are unknown"))
        assert "- ADR-0077 and ADR-0084:" in report(root)

    def test_prose_after_the_section_is_not_a_row(self, root):
        similar_pair(root)
        readme(root)
        assert "- ADR-0077 and ADR-0084:" in report(root)

    def test_no_readme_means_nothing_is_kept(self, root):
        similar_pair(root)
        assert tool.kept_separate(root) == ([], [])
        assert "- ADR-0077 and ADR-0084:" in report(root)
