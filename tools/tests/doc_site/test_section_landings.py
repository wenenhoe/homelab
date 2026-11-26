"""The landing of each section, and the breadcrumb that tells a page where it is in its section."""

from __future__ import annotations

import re

import pytest
from _doc_fixtures import project, revision
from doc_site import site


def build(tree) -> dict[str, str]:
    return {path: data.decode() for path, data in site.build(tree).items() if path.endswith(".html")}


def crumbs(html: str) -> list[tuple[str, str | None]]:
    nav = re.search(r'<nav class="crumbs".*?</nav>', html, re.S)
    assert nav
    return [
        (label or span, href or None) for href, label, span in re.findall(r'<li>(?:<a href="([^"]*)">([^<]*)</a>|<span[^>]*>([^<]*)</span>)</li>', nav.group(0))
    ]


def test_the_projects_landing_lists_the_projects_with_status_and_initiative_above_the_readme(tree):
    out = build(tree)["projects/index.html"]
    assert out.index('id="project-list"') < out.index('<h2 id="guide">Guide to projects</h2>')
    assert '<a href="../projects/one/"><code>one</code></a>' in out
    assert '<span class="pill s-building">Building</span>' in out
    assert 'data-label="Initiative">base</td>' in out


def test_the_projects_list_orders_by_status_then_source(tree):
    project(tree, "aaa", status="done")
    out = build(tree)["projects/index.html"]
    names = re.findall(r'<td class="title" data-label="Project"><a href="\.\./projects/([^/]+)/">', out)
    assert names[-1] == "aaa"
    assert names[:-1] == sorted(names[:-1], key=lambda n: (out.index(f"projects/{n}/"), n))


def test_a_summary_with_a_pipe_stays_in_its_cell(tree):
    project(tree, "piped", summary="reads `a | b` as one")
    out = build(tree)["projects/piped/index.html"]
    assert "a | b" in out
    assert "a | b" in build(tree)["projects/index.html"]


def test_the_projects_landing_links_the_guide_and_its_menu_lists_the_list_and_the_guide(tree):
    out = build(tree)["projects/index.html"]
    assert '<a class="guide" href="../projects/#guide">Guide to projects</a>' in out
    assert '<a href="#project-list">The projects</a><a href="#guide">Guide to projects</a>' in out


def test_a_landing_is_not_a_link_to_itself_and_a_page_below_it_links_back(tree):
    files = build(tree)
    assert crumbs(files["projects/index.html"]) == [("Projects", None)]
    assert crumbs(files["projects/one/index.html"])[0] == ("Projects", "../../projects/")
    assert crumbs(files["projects/one/index.html"])[-1] == ("one", None)


def test_decisions_land_on_the_index_and_the_readme_of_decisions_is_its_guide(tree):
    revision(tree, "0001-a", 0)
    (tree / "docs/decisions/README.md").write_text("# Decisions\n\nHow they work.\n", encoding="utf-8")
    files = build(tree)
    assert crumbs(files["decisions/index.html"]) == [("Decisions", "../decision-index/"), ("Guide", None)]
    assert crumbs(files["decision-index/index.html"]) == [("Decisions", None)]
    assert '<a class="guide" href="../decisions/">Guide to decisions</a>' in files["decision-index/index.html"]


def test_a_revision_names_its_adr_and_revision(tree):
    revision(tree, "0001-a", 0)
    trail = crumbs(build(tree)["decisions/0001-a/revision-000/index.html"])
    assert [label for label, _ in trail] == ["Decisions", "ADR 0001", "revision 0"]


def test_a_topic_page_names_its_group_when_the_topics_readme_has_that_anchor(tree):
    files = build(tree)
    assert crumbs(files["topics/infra/network/index.html"])[0] == ("Topics", "../../../topics/")
    assert crumbs(files["topics/index.html"]) == [("Topics", None)]


def test_architecture_pages_sit_under_the_architecture_entry(tree):
    files = build(tree)
    assert crumbs(files["architecture/index.html"]) == [("Architecture", None)]
    assert crumbs(files["architecture/flow/index.html"])[0] == ("Architecture", "../../architecture/")


@pytest.mark.parametrize(("page", "label"), [("project-planning", "Planning"), ("dr-coverage", "DR coverage")])
def test_a_view_outside_every_section_names_itself_in_its_breadcrumb(tree, page, label):
    assert crumbs(build(tree)[f"{page}/index.html"]) == [(label, None)]
