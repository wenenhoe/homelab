"""The decision revisions as pages: a header from the front matter, the mark of a superseded one and the links into and out of them."""

from __future__ import annotations

import re

import pytest
from _doc_fixtures import project, revision
from doc_site import site
from doc_site.markup import REPO_URL, UnsupportedMarkup


def build(tree):
    return site.build(tree)


def page(tree, path: str = "0001-a/revision-000") -> str:
    return build(tree)[f"decisions/{path}/index.html"].decode()


def test_each_revision_has_a_page_at_its_path_and_a_candidate_has_its_own(tree):
    revision(tree, "0003-c", 0, letter="a")
    revision(tree, "0003-c", 0, letter="b")
    pages = {path for path in build(tree) if path.startswith("decisions/")}
    assert pages == {
        "decisions/0001-a/revision-000/index.html",
        "decisions/0002-b/revision-000/index.html",
        "decisions/0003-c/revision-000-a/index.html",
        "decisions/0003-c/revision-000-b/index.html",
    }


def test_the_readme_and_the_list_of_removed_numbers_have_pages_and_the_templates_have_none(tree):
    for name in ("README", "removed", "TEMPLATE", "TEMPLATE-light"):
        (tree / f"docs/decisions/{name}.md").write_text(f"# {name}\n", encoding="utf-8")
    pages = {path for path in build(tree) if path.startswith("decisions/") and "/revision-" not in path}
    assert pages == {"decisions/index.html", "decisions/removed/index.html"}


def test_the_header_names_the_record_and_its_state(tree):
    out = page(tree)
    assert "<dt>Record</dt><dd>ADR 0001, revision 0</dd>" in out
    assert '<dt>State</dt><dd><span class="pill s-approved">approved</span></dd>' in out
    assert '<p class="lede">Where secrets live.</p>' in out
    assert "<dt>Weight</dt>" not in out


def test_a_light_record_says_so(tree):
    revision(tree, "0003-c", 0, weight="light")
    assert "<dt>Weight</dt><dd>light</dd>" in page(tree, "0003-c/revision-000")


def test_a_superseded_revision_is_marked_and_names_its_successor(tree):
    revision(tree, "0001-a", 0, status="superseded", superseded_by=1, short="Old")
    revision(tree, "0001-a", 1, status="accepted", supersedes=0, short="New")
    old = page(tree, "0001-a/revision-000")
    assert '<span class="pill s-superseded">superseded</span>' in old
    assert '<dt>Superseded by</dt><dd><a href="../../../decisions/0001-a/revision-001/">revision 1 (New)</a></dd>' in old
    assert '<p class="notice">This revision is superseded by <a href="../../../decisions/0001-a/revision-001/">revision 1 (New)</a>.' in old
    new = page(tree, "0001-a/revision-001")
    assert '<dt>Supersedes</dt><dd><a href="../../../decisions/0001-a/revision-000/">revision 0 (Old)</a></dd>' in new
    assert 'class="notice"' not in new


def test_a_revision_that_relies_on_another_links_to_the_current_revision_of_that_lineage_with_the_reason(tree):
    revision(tree, "0003-c", 0, relies_on=[{"adr": "ADR-0001", "reason": "the proxy stays"}], short="Third")
    revision(tree, "0001-a", 0, status="accepted", short="First")
    out = page(tree, "0003-c/revision-000")
    link = '<a href="../../../decisions/0001-a/revision-000/">ADR 0001 (First)</a>'
    assert f'<dt>Relies on</dt><dd><span class="rely">{link}<span class="why">the proxy stays</span></span></dd>' in out


def test_related_and_narrowed_lineages_are_links(tree):
    revision(tree, "0003-c", 0, related=["ADR-0002"], narrows="ADR-0001")
    out = page(tree, "0003-c/revision-000")
    assert '<dt>Related</dt><dd><a href="../../../decisions/0002-b/revision-000/">ADR 0002 (0002-b)</a></dd>' in out
    assert '<dt>Narrows</dt><dd><a href="../../../decisions/0001-a/revision-000/">ADR 0001 (0001-a)</a></dd>' in out


def test_a_lineage_that_is_gone_is_named_and_not_linked(tree):
    revision(tree, "0003-c", 0, relies_on=[{"adr": "ADR-0099", "reason": "it held the boundary"}])
    assert '<span class="rely">ADR 0099<span class="why">it held the boundary</span></span>' in page(tree, "0003-c/revision-000")


def test_the_projects_that_implement_a_revision_are_linked_by_either_field(tree):
    project(tree, "three", also_implements=["ADR-0001/0"], decision="ADR-0002/0")
    out = page(tree)
    assert '<dt>Implemented by</dt><dd><a href="../../../projects/one/">one</a>, <a href="../../../projects/three/">three</a></dd>' in out
    assert '<dt>Implemented by</dt><dd><a href="../../../projects/three/">three</a></dd>' in page(tree, "0002-b/revision-000")


def test_a_revision_no_project_names_has_no_implemented_by(tree):
    revision(tree, "0003-c", 0)
    assert "<dt>Implemented by</dt>" not in page(tree, "0003-c/revision-000")


def test_a_link_between_revisions_keeps_its_anchor_and_a_link_to_a_project_reaches_its_page(tree):
    revision(tree, "0003-c", 0, body="# Third\n\nSee [the second](../0002-b/revision-000.md#decision) and [the project](../../projects/one.md).\n")
    out = page(tree, "0003-c/revision-000")
    assert 'href="../../../decisions/0002-b/revision-000/#decision"' in out
    assert 'href="../../../projects/one/"' in out


def test_the_decision_index_links_its_rows_to_the_pages(tree):
    out = build(tree)["decision-index/index.html"].decode()
    assert 'href="../decisions/0001-a/revision-000/"' in out


def test_a_decision_page_is_under_decisions_in_the_navigation(tree):
    out = page(tree)
    assert re.search(r'<a href="\.\./\.\./\.\./decision-index/" aria-current="page">Decisions</a>', out)
    assert 'aria-current="page">Projects<' not in out


def test_every_page_links_to_its_file_on_github_and_reaches_its_assets_from_its_depth(tree):
    out = page(tree)
    assert f'<a href="{REPO_URL}/blob/main/docs/decisions/0001-a/revision-000.md">View this file on GitHub</a>' in out
    assert re.search(r'href="\.\./\.\./\.\./assets/site\.[0-9a-f]{10}\.css"', out)


def test_the_anchors_a_link_can_name_include_the_decision_pages(tree):
    revision(tree, "0003-c", 0, body="# Third\n\n## Decision\n")
    assert "decision" in site.page_anchors(tree)["decisions/0003-c/revision-000"]


def test_a_revision_with_markup_the_renderer_refuses_stops_the_build(tree):
    revision(tree, "0003-c", 0, body="# Third\n\n<div>x</div>\n")
    with pytest.raises(UnsupportedMarkup, match=r"0003-c/revision-000\.md"):
        build(tree)
