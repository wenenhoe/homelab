"""A decision page lists every revision of its lineage and links to the decisions before and after it by number."""

from __future__ import annotations

import re

from _doc_fixtures import revision
from doc_site import site


def page(tree, path: str) -> str:
    return site.build(tree)[f"decisions/{path}/index.html"].decode()


def strip(html: str) -> str:
    match = re.search(r'<nav class="lineage".*?</nav>', html, re.S)
    return match.group(0) if match else ""


def test_a_lineage_of_one_revision_has_no_strip(tree):
    revision(tree, "0001-a", 0)
    assert strip(page(tree, "0001-a/revision-000")) == ""


def test_the_strip_lists_every_revision_with_its_state_and_marks_the_current_one_and_this_page(tree):
    revision(tree, "0001-a", 0, status="superseded", superseded_by=1, short="Old")
    revision(tree, "0001-a", 1, status="accepted", supersedes=0, short="New")
    out = strip(page(tree, "0001-a/revision-000"))
    assert re.findall(r'<li class="([^"]*)">', out) == ["here", "current"]
    assert '<a href="../../../decisions/0001-a/revision-001/">revision 1 (New)</a>' in out
    assert "revision 0 (Old)</li>" not in out
    assert '<span class="pill s-superseded">superseded</span><span class="mark">this page</span>' in out
    assert '<span class="pill s-accepted">accepted</span><span class="mark">current</span>' in out


def test_the_strip_on_the_current_revision_names_the_earlier_one_as_a_link(tree):
    revision(tree, "0001-a", 0, status="superseded", superseded_by=1, short="Old")
    revision(tree, "0001-a", 1, status="accepted", supersedes=0, short="New")
    out = strip(page(tree, "0001-a/revision-001"))
    assert '<a href="../../../decisions/0001-a/revision-000/">revision 0 (Old)</a>' in out
    assert re.findall(r'<li class="([^"]*)">', out) == ["", "here current"]


def test_the_pager_links_the_neighbours_by_number_at_their_current_revision(tree):
    revision(tree, "0001-a", 0, short="First")
    revision(tree, "0002-b", 0, status="superseded", superseded_by=1, short="Old")
    revision(tree, "0002-b", 1, status="accepted", supersedes=0, short="Second")
    revision(tree, "0003-c", 0, short="Third")
    out = page(tree, "0002-b/revision-001")
    assert '<span class="prev"><a href="../../../decisions/0001-a/revision-000/">← ADR 0001</a><span class="name">First</span></span>' in out
    assert '<span class="next"><a href="../../../decisions/0003-c/revision-000/">ADR 0003 →</a><span class="name">Third</span></span>' in out
    assert 'href="../../../decisions/0002-b/revision-000/">←' not in out


def test_the_first_and_last_decision_have_one_side_only(tree):
    revision(tree, "0001-a", 0)
    revision(tree, "0002-b", 0)
    assert 'class="prev"' not in page(tree, "0001-a/revision-000")
    assert 'class="next"' in page(tree, "0001-a/revision-000")
    assert 'class="next"' not in page(tree, "0002-b/revision-000")
