"""The decision index on the site: the numbers ten to a row, and the topic groups as tabs that need no script."""

from __future__ import annotations

import re

from _doc_fixtures import revision
from doc_site import site


def index(tree) -> str:
    return site.build(tree)["decision-index/index.html"].decode()


def cells(html: str) -> list[tuple[str, str]]:
    grid = html[html.index('<div class="numbers">') :]
    return re.findall(r'<li class="n-([a-z]+)">(.*?)</li>', grid[: grid.index("</div></div>") + 12])


def test_the_numbers_are_ten_to_a_row_each_row_labelled(tree):
    html = index(tree)
    rows = re.findall(r'<div class="num-row"><span class="num-label">([^<]+)</span><ol>(.*?)</ol></div>', html)
    assert [label for label, _ in rows] == ["000x"]
    assert all(items.count("<li ") == 10 for _, items in rows)


def test_a_lineage_is_a_link_to_its_page_and_the_gaps_around_it_are_marked(tree):
    found = cells(index(tree))
    assert found[0] == ("none", "")
    assert found[1] == ("live", '<a href="../decisions/0001-a/revision-000/">0001</a>')
    assert found[2][0] == "live"
    assert [kind for kind, _ in found[3:]] == ["none"] * 7


def test_a_merged_number_names_where_it_went_with_a_link(tree):
    revision(tree, "0003-c", 0, status="accepted", former_ids=["ADR-0007"])
    found = dict(enumerate(cells(index(tree))))
    assert found[7] == ("merged", '0007 → <a href="../decisions/0003-c/revision-000/">0003</a>')


def test_the_decisions_count_is_the_lineages_and_not_the_other_numbers(tree):
    html = index(tree)
    assert re.search(r"<strong>2</strong><span>Decisions</span>", html)


def test_the_topic_groups_are_tabs_each_a_link_beside_its_panel_with_the_heading_anchor(tree):
    revision(tree, "0003-c", 0, topic="deployment-platform", status="accepted")
    html = index(tree)
    tabs = re.findall(r'<div class="tab"><a class="tab-link" href="#([^"]+)">([^<]+)</a><div class="panel"><h3 id="([^"]+)">', html)
    assert [(a, label) for a, label, _ in tabs] == [("deployment--platform", "Deployment &amp; platform"), ("secrets-store", "Secrets store")]
    assert all(anchor == heading for anchor, _, heading in tabs)


def test_a_lineage_is_in_exactly_one_topic_group_and_in_the_grid(tree):
    revision(tree, "0003-c", 0, topic="deployment-platform", status="accepted")
    html = index(tree)
    panels = re.findall(r'<div class="panel">(.*?)</div></div>', html, re.S)
    for number in ("0001", "0002", "0003"):
        assert sum(f'">{number}</a>' in panel for panel in panels) == 1
        assert f'">{number}</a></li>' in html


def test_a_topic_row_has_the_short_name_before_the_problem_and_the_solution(tree):
    html = index(tree)
    assert re.search(r'data-label="Decision">[^<]+</td><td class="field" data-label="Problem">', html)
    assert "<th>Decision</th><th>Problem</th><th>Current solution</th>" in html


def test_the_stylesheet_hides_a_panel_only_by_selectors_and_shows_every_group_while_filtering():
    css = (site.PACKAGE / "assets/site.css").read_text(encoding="utf-8")
    assert ".tab>.panel{" in css and "display:none" in css[css.index(".tab>.panel{") :][:120]
    assert ".tabs.filtering>.tab>.panel{display:block}" in css
    script = (site.PACKAGE / "assets/site.js").read_text(encoding="utf-8")
    assert "filtering" in script
