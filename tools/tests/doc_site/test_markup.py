"""The markdown subset, GitHub's heading anchors and the links between views."""

from __future__ import annotations

from typing import ClassVar

import pytest
from doc_site.markup import REPO_URL, Anchors, UnsupportedMarkup, github_slug, inline, link_resolver, paragraphs


def keep(target: str) -> str:
    return target


class TestGithubSlug:
    @pytest.mark.parametrize(
        ("heading", "slug"),
        [
            ("By number", "by-number"),
            ("Decisions awaiting a project", "decisions-awaiting-a-project"),
            ("Open `ADR` decisions", "open-adr-decisions"),
            ("Apps (all)", "apps-all"),
            ("DR: tier 1 / tier 2", "dr-tier-1--tier-2"),
            ("snake_case stays", "snake_case-stays"),
            ("A [link](x.md) here", "a-link-here"),
        ],
    )
    def test_the_anchor_github_gives(self, heading, slug):
        assert github_slug(heading) == slug

    def test_a_repeated_heading_is_numbered_like_github_does(self):
        anchors = Anchors()
        assert [anchors.of("Notes"), anchors.of("Notes"), anchors.of("Notes")] == ["notes", "notes-1", "notes-2"]


class TestInline:
    def test_code_bold_and_links(self):
        assert inline("`a<b` and **c** and [d](e.md)", keep) == '<code>a&lt;b</code> and <strong>c</strong> and <a href="e.md">d</a>'

    def test_text_is_escaped(self):
        assert inline("1 < 2 & 3", keep) == "1 &lt; 2 &amp; 3"

    def test_an_escaped_pipe_is_a_pipe(self):
        assert inline("a \\| b", keep) == "a | b"

    def test_a_link_target_goes_through_the_resolver(self):
        assert inline("[x](y.md)", str.upper) == '<a href="Y.MD">x</a>'

    def test_a_link_text_may_hold_code(self):
        assert inline("[`x.md`](x.md)", keep) == '<a href="x.md"><code>x.md</code></a>'


class TestParagraphs:
    def test_a_wrapped_paragraph_is_one_line(self):
        assert paragraphs("one\ntwo\n\nthree", keep) == ["one two", "three"]

    @pytest.mark.parametrize("line", ["- item", "1. item", "> quote", "```", "| a | b |", "## heading", "<div>", "    indented"])
    def test_other_markup_is_refused(self, line):
        with pytest.raises(UnsupportedMarkup):
            paragraphs(f"text\n\n{line}", keep)


class TestLinkResolver:
    PAGES: ClassVar[dict[str, str]] = {"docs/decision-index.md": "../decision-index/", "docs/project-planning.md": "../project-planning/"}

    def resolver(self, directories=("docs/projects",)):
        return link_resolver("docs/project-planning.md", self.PAGES, lambda path: path in directories)

    def test_a_link_to_another_view_goes_to_its_page_and_keeps_the_anchor(self):
        assert self.resolver()("decision-index.md#by-number") == "../decision-index/#by-number"

    def test_a_link_to_another_file_goes_to_github(self):
        assert self.resolver()("projects/a.md") == f"{REPO_URL}/blob/main/docs/projects/a.md"

    def test_a_link_to_a_directory_goes_to_the_directory(self):
        assert self.resolver()("projects") == f"{REPO_URL}/tree/main/docs/projects"

    def test_a_link_with_a_scheme_or_a_fragment_is_unchanged(self):
        resolve = self.resolver()
        assert (resolve("https://example.com/x"), resolve("#here")) == ("https://example.com/x", "#here")

    def test_a_link_out_of_the_repository_is_refused(self):
        with pytest.raises(UnsupportedMarkup):
            self.resolver()("../../../etc/passwd")
