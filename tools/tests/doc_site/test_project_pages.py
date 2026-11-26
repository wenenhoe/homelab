"""The projects as pages: a header from the front matter, links between them and the source link."""

from __future__ import annotations

import re

import pytest
from _doc_fixtures import project, write_doc
from doc_site import site
from doc_site.markup import REPO_URL, UnsupportedMarkup


def page(tree, name: str) -> str:
    return site.build(tree)[f"projects/{name}/index.html"].decode()


def test_each_project_has_a_page_and_so_does_the_readme_but_the_template_has_none(tree):
    (tree / "docs/projects/TEMPLATE.md").write_text("not a document\n", encoding="utf-8")
    pages = {path for path in site.build(tree) if path.startswith("projects/")}
    assert pages == {"projects/index.html", "projects/one/index.html", "projects/two/index.html"}


def test_the_header_is_the_front_matter(tree):
    out = page(tree, "one")
    assert '<span class="pill s-building">building</span>' in out
    assert "<dt>Decision</dt><dd><code>ADR-0001/0</code></dd>" in out
    assert "<dt>Part of</dt><dd><code>base</code></dd>" in out
    assert '<p class="lede">one summary</p>' in out


def test_a_project_that_waits_on_another_links_to_its_page(tree):
    project(tree, "three", depends_on=[{"project": "PROJ-one", "reason": "needs its output"}])
    assert '<dt>Waits on</dt><dd><a href="../../projects/one/">one</a></dd>' in page(tree, "three")


def test_every_page_links_to_its_file_on_github(tree):
    assert f'<a href="{REPO_URL}/blob/main/docs/projects/one.md">View this file on GitHub</a>' in page(tree, "one")


def test_a_link_between_projects_and_a_link_to_a_view_reach_their_pages(tree):
    write_doc(
        tree,
        "docs/projects/four.md",
        {"id": "PROJ-four", "title": "four", "type": "project", "status": "not-started", "summary": "four"},
        "# Four\n\n[one](one.md#scope) and [the index](../decision-index.md#by-number).\n",
    )
    out = page(tree, "four")
    assert 'href="../../projects/one/#scope"' in out
    assert 'href="../../decision-index/#by-number"' in out


def test_a_page_reaches_the_assets_and_the_home_from_its_depth(tree):
    out = page(tree, "one")
    assert re.search(r'href="\.\./\.\./assets/site\.[0-9a-f]{10}\.css"', out)
    assert 'class="brand" href="../../"' in out
    assert '<a href="../../project-planning/">Planning</a>' in out


def test_the_planning_view_links_its_chips_to_the_project_pages(tree):
    out = site.build(tree)["project-planning/index.html"].decode()
    assert 'href="../projects/one/"' in out


def test_the_anchors_a_link_can_name_include_the_project_pages(tree):
    write_doc(
        tree,
        "docs/projects/four.md",
        {"id": "PROJ-four", "title": "four", "type": "project", "status": "not-started", "summary": "four"},
        "# Four\n\n## Scope\n",
    )
    assert "scope" in site.page_anchors(tree)["projects/four"]


def test_a_project_with_markup_the_renderer_refuses_stops_the_build(tree):
    write_doc(
        tree,
        "docs/projects/four.md",
        {"id": "PROJ-four", "title": "four", "type": "project", "status": "not-started", "summary": "four"},
        "# Four\n\n<div>x</div>\n",
    )
    with pytest.raises(UnsupportedMarkup, match=r"four\.md"):
        site.build(tree)


def project_list(tree) -> str:
    html = site.build(tree)["projects/index.html"].decode()
    return html[html.index('<section id="project-list">') : html.index('<h2 id="guide">')]


def test_the_projects_not_started_are_in_a_block_that_is_open_in_the_markup(tree):
    listing = project_list(tree)
    before, folded = listing.split('<details class="fold" open><summary>Not started (1)</summary>')
    assert "one/" in before and "two/" not in before
    assert "two/" in folded


def test_a_list_with_nothing_waiting_has_no_block(tree):
    (tree / "docs/projects/two.md").unlink()
    assert "<details" not in project_list(tree)
