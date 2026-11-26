"""A long page lists its headings, and the Topics index shows its groups as tabs."""

from __future__ import annotations

import re
import shutil

import pytest
from doc_site import layout, site
from doc_site.diagrams import Drawn

LONG = "# A long page\n\nIntro.\n\n" + "".join(f"## Part {n}\n\nText.\n\n### Detail {n}\n\nMore.\n\n" for n in range(1, 4))
SHORT = "# A short page\n\n## One\n\ntext\n\n## Two\n\ntext\n\n### Three\n\ntext\n"
GROUPS = (
    "# Topics\n\nIntro with [a link](infra/network.md).\n\n"
    "## deploy/\n\nDeploying.\n\n| Doc | Covers |\n| :--- | :--- |\n| [`a.md`](deploy/a.md) | The first. |\n\n"
    "## infra/\n\nMachines.\n\n| Doc | Covers |\n| :--- | :--- |\n| [`network.md`](infra/network.md) | The network. |\n"
)


def fake(sources: list[str]) -> list[Drawn]:
    return [Drawn("<svg></svg>", "<svg></svg>") for _ in sources]


def built(tree, **pages: str) -> dict[str, str]:
    """The pages of the tree, after writing each of `pages` (the topics README as `readme`, the network doc as `network`) into it."""
    for name, text in pages.items():
        (tree / {"readme": "docs/topics/README.md", "network": "docs/topics/infra/network.md"}[name]).write_text(text, encoding="utf-8")
    return {path: data.decode() for path, data in site.build(tree, draw=fake).items() if path.endswith(".html")}


def contents_of(html: str) -> str:
    return re.search(r'<nav class="toc".*?</nav>', html, re.DOTALL)[0]


def test_a_page_with_four_headings_lists_them_on_the_page(tree):
    html = built(tree, network=LONG)["topics/infra/network/index.html"]
    contents = contents_of(html)
    assert "<details open><summary>On this page</summary>" in contents
    assert '<a href="#part-1">Part 1</a>' in contents and '<a href="#detail-1" class="sub">Detail 1</a>' in contents
    assert html.index('class="toc"') < html.index('<article class="doc">')


def test_a_page_with_fewer_than_four_headings_has_no_list(tree):
    assert 'class="toc"' not in built(tree, network=SHORT)["topics/infra/network/index.html"]


def test_each_second_level_heading_links_back_to_the_list_and_a_third_level_does_not(tree):
    html = built(tree, network=LONG)["topics/infra/network/index.html"]
    assert html.count('<a class="up" href="#on-this-page">') == 3
    assert re.search(r'<h2 id="part-1">Part 1 <a class="up" href="#on-this-page">', html)
    assert re.search(r'<h3 id="detail-1">Detail 1</h3>', html)


def test_the_list_is_made_from_the_headings_and_changes_no_source_file(tree):
    built(tree, network=LONG)
    before = LONG
    assert (tree / "docs/topics/infra/network.md").read_text(encoding="utf-8") == before


def test_a_heading_with_the_anchor_of_the_list_stops_the_build(tree):
    with pytest.raises(ValueError, match="anchor of the list of headings"):
        built(tree, network=LONG + "## On this page\n\ntext\n")


def test_the_topics_index_shows_each_group_as_a_tab_beside_its_panel(tree):
    html = built(tree, readme=GROUPS)["topics/index.html"]
    assert '<div class="tab"><a class="tab-link" href="#deploy">deploy/</a><div class="panel"><h2 id="deploy">deploy/</h2>' in html
    assert '<div class="tab"><a class="tab-link" href="#infra">infra/</a><div class="panel"><h2 id="infra">infra/</h2>' in html
    assert html.index("Intro with") < html.index('id="q"') < html.index('<div class="tabs">')
    assert 'class="toc"' not in html


def test_a_topic_pages_breadcrumb_group_is_a_tab_of_the_index(tree):
    html = built(tree, readme=GROUPS)
    assert 'href="../../../topics/#infra"' in html["topics/infra/network/index.html"]
    assert 'id="infra"' in html["topics/index.html"]


def test_no_other_document_is_tabbed(tree):
    assert 'class="tabs"' not in built(tree, network=GROUPS)["topics/infra/network/index.html"]


def test_the_topics_index_without_groups_is_not_tabbed(tree):
    assert 'class="tabs"' not in built(tree)["topics/index.html"]


def test_every_group_is_in_the_markup_so_that_all_show_without_the_stylesheet(tree):
    html = built(tree, readme=GROUPS)["topics/index.html"]
    assert "hidden" not in html.split('<div class="tabs">')[1] and html.count('class="panel"') == 2


needs_chrome = pytest.mark.skipif(shutil.which("google-chrome") is None, reason="the layout check drives the installed Google Chrome")


@needs_chrome
def test_the_list_is_closed_on_a_narrow_screen_and_open_on_a_wide_one(tree, tmp_path):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    built(tree, network=LONG)
    out = tmp_path / "site"
    site.write(out, tree)
    with layout.serving(out) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 800})
            page.goto(f"{base}/topics/infra/network/")
            assert page.evaluate("document.querySelector('.toc details').open") is False
            page.set_viewport_size({"width": 1280, "height": 800})
            page.evaluate("() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
            assert page.evaluate("document.querySelector('.toc details').open") is True
            box = page.evaluate("[document.querySelector('.toc').getBoundingClientRect().left, document.querySelector('.doc').getBoundingClientRect().right]")
            assert box[0] >= box[1]
        finally:
            browser.close()


@needs_chrome
@pytest.mark.parametrize(("width", "beside"), [pytest.param(1040, True, id="breakpoint"), pytest.param(1039, False, id="below")])
def test_the_list_moves_beside_the_prose_at_the_breakpoint(tree, tmp_path, width, beside):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    built(tree, network=LONG)
    out = tmp_path / "site"
    site.write(out, tree)
    with layout.serving(out) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            page = browser.new_page(viewport={"width": width, "height": 800})
            page.goto(f"{base}/topics/infra/network/")
            box = page.evaluate("[document.querySelector('.toc').getBoundingClientRect().left, document.querySelector('.doc').getBoundingClientRect().right]")
            assert (box[0] >= box[1]) is beside
            assert page.evaluate("document.querySelector('.toc details').open") is beside
        finally:
            browser.close()


MANY = "# Many\n\n" + "".join(f"## Part {n}\n\n" + "Text.\n\n" * 5 for n in range(1, 31))
# The contents list, where it is on the screen and how much of it is out of sight in its own box.
LIST_BOX = """() => {
  const list = document.querySelector('.toc');
  const box = list.getBoundingClientRect();
  return {top: box.top, bottom: box.bottom, hidden: list.scrollHeight - list.clientHeight};
}"""


@needs_chrome
@pytest.mark.parametrize(("height", "top"), [pytest.param(800, 72, id="under-the-header"), pytest.param(420, 8, id="short-screen")])
def test_a_list_beside_the_prose_stays_on_screen_and_scrolls_on_its_own(tree, tmp_path, height, top):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    built(tree, network=MANY)
    out = tmp_path / "site"
    site.write(out, tree)
    with layout.serving(out) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            page = browser.new_page(viewport={"width": 1280, "height": height})
            page.goto(f"{base}/topics/infra/network/")
            page.evaluate("window.scrollTo({top: document.documentElement.scrollHeight / 2, behavior: 'instant'})")
            box = page.evaluate(LIST_BOX)
            assert box["top"] == pytest.approx(top, abs=1)
            assert box["bottom"] <= height
            assert box["hidden"] > 0
            assert page.locator("h2 .up").first.is_hidden()
            page.set_viewport_size({"width": 390, "height": height})
            assert page.locator("h2 .up").first.is_visible()
        finally:
            browser.close()


# The width of main's content, and the space on each side of main.
COLUMN = """() => {
  const main = document.querySelector('main'), box = main.getBoundingClientRect(), style = getComputedStyle(main);
  return [box.width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight), box.left, document.documentElement.clientWidth - box.right];
}"""


@needs_chrome
@pytest.mark.parametrize(
    ("network", "path", "width", "column"),
    [
        pytest.param(SHORT, "topics/infra/network/", 1920, 848, id="no-list"),
        pytest.param(LONG, "topics/infra/network/", 1000, 848, id="list-above"),
        pytest.param(LONG, "topics/infra/network/", 1920, 1120, id="list-beside"),
        pytest.param(SHORT, "decision-index/", 1920, 1120, id="view"),
    ],
)
def test_a_document_without_a_list_beside_it_is_a_centred_column(tree, tmp_path, network, path, width, column):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    built(tree, network=network)
    out = tmp_path / "site"
    site.write(out, tree)
    with layout.serving(out) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            page = browser.new_page(viewport={"width": width, "height": 800})
            page.goto(f"{base}/{path}")
            content, left, right = page.evaluate(COLUMN)
            assert content == pytest.approx(column, abs=1)
            assert left == pytest.approx(right, abs=1)
        finally:
            browser.close()


KEYED = "# Keys\n\n| Name | Does |\n| --- | --- |\n| `an_identifier_of_some_length` | " + "words " * 60 + "|\n"
# The number of lines the first code span of a table takes.
KEY_LINES = "() => document.querySelector('.doc td code').getClientRects().length"


@needs_chrome
def test_an_identifier_that_names_a_row_is_not_cut(tree, tmp_path):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    built(tree, network=KEYED)
    out = tmp_path / "site"
    site.write(out, tree)
    with layout.serving(out) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            page = browser.new_page(viewport={"width": 1040, "height": 800})
            page.goto(f"{base}/topics/infra/network/")
            assert page.evaluate(KEY_LINES) == 1
        finally:
            browser.close()


@needs_chrome
def test_a_site_with_a_long_page_and_tabs_fits_every_width(tree, tmp_path):
    pytest.importorskip("playwright")
    built(tree, network=LONG, readme=GROUPS)
    out = tmp_path / "site"
    site.write(out, tree)
    assert layout.check(out) == []
