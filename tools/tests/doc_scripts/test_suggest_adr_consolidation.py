"""Tests for suggest_adr_consolidation.py: each signal on a throwaway tree.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from datetime import date, timedelta

from _doc_fixtures import GitRepo, project, revision
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
        out = tool.render(root, report=False, today=date.today())
        assert "# Decision records worth a look" in out
        assert "Quarterly report" not in out

    def test_the_report_names_a_working_revision_left_alone(self, root):
        repo = GitRepo(root, tool)
        repo.git("init", "-q", "-b", "main")
        revision(root, "0001-a", 0, status="working")
        repo.commit("add")
        later = date.today() + timedelta(days=tool.WORKING_STALE_DAYS + 5)
        out = tool.render(root, report=True, today=later)
        assert "ADR-0001 revision 0: working, unchanged for" in out

    def test_the_report_flags_too_many_active_projects(self, root):
        from doc_scripts import generate_doc_indexes as gen

        for i in range(gen.ACTIVE_PROJECT_LIMIT + 1):
            project(root, f"p{i}", status="building")
        assert "over the limit" in tool.render(root, report=True, today=date.today())
