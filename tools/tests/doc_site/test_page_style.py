"""What a reader sees of a page's headings, header and names, measured in a browser."""

from __future__ import annotations

import contextlib
import shutil

import pytest
from doc_site import layout, site
from doc_site.diagrams import Drawn

pytestmark = pytest.mark.skipif(shutil.which("google-chrome") is None, reason="the pages are measured in the installed Google Chrome")


def drawn(sources: list[str]) -> list[Drawn]:
    return [Drawn("<svg></svg>", "<svg></svg>") for _ in sources]


@contextlib.contextmanager
def opened(files: dict[str, bytes], out, path: str, width: int, height: int = 800):
    sync_api = pytest.importorskip("playwright.sync_api")
    from doc_site import chrome

    for name, data in files.items():
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(data)
    with layout.serving(out) as base, sync_api.sync_playwright() as playwright:
        browser = chrome.launch(playwright)
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(f"{base}/{path}")
            yield page
        finally:
            browser.close()


def test_a_heading_is_smaller_than_the_one_above_it_in_rank(tree, tmp_path):
    (tree / "docs/topics/infra/network.md").write_text("# One\n\n## Two\n\ntext\n\n### Three\n\ntext\n\n#### Four\n\ntext\n", encoding="utf-8")
    with opened(site.build(tree, draw=drawn), tmp_path, "topics/infra/network/", 1280) as page:
        sizes = page.evaluate("['h1','h2','h3','h4'].map((tag) => parseFloat(getComputedStyle(document.querySelector('main ' + tag)).fontSize))")
    assert sizes == sorted(sizes, reverse=True) and len(set(sizes)) == 4


@pytest.mark.parametrize("width", [390, 1280])
def test_the_header_starts_at_the_top_of_the_page(tree, tmp_path, width):
    with opened(site.build(tree, draw=drawn), tmp_path, "", width) as page:
        assert page.evaluate("document.querySelector('header.bar').getBoundingClientRect().top") == 0


# The lines a code span's text is drawn on.
LINES = """(element) => {
  const range = document.createRange();
  range.selectNodeContents(element);
  return new Set([...range.getClientRects()].map((box) => Math.round(box.top))).size;
}"""


def test_a_name_that_titles_a_row_of_a_view_is_not_cut(tree, tmp_path):
    files = site.build(tree, draw=drawn)
    long = "<code>seaweedfsandthensome</code>"
    cells = "".join(f'<td class="field" data-label="C{n}">several words that all want some room of their own here</td>' for n in range(6))
    table = f'<table><tbody><tr><td class="title" data-label="App">{long}</td>{cells}</tr></tbody></table>'
    html = files["dr-coverage/index.html"].decode()
    files["dr-coverage/index.html"] = html.replace("</main>", f'<section id="probe">{table}</section></main>').encode()
    with opened(files, tmp_path, "dr-coverage/", 1040) as page:
        assert page.locator("#probe td.title code").evaluate(LINES) == 1


def test_a_code_span_of_a_space_alone_stays_within_its_paragraph(tree, tmp_path):
    # A paragraph for each length of lead-in, so that in some of them the span falls at the end of a line.
    text = "# Spaces\n\n" + "".join(f"with {'i ' * count}` `, and more words\n\n" for count in range(1, 120))
    (tree / "docs/topics/infra/network.md").write_text(text, encoding="utf-8")
    with opened(site.build(tree, draw=drawn), tmp_path, "topics/infra/network/", 360) as page:
        wider = page.evaluate("[...document.querySelectorAll('article.doc p')].filter((p) => p.scrollWidth > p.clientWidth).length")
    assert wider == 0


@pytest.mark.parametrize(("width", "open_"), [pytest.param(390, False, id="phone"), pytest.param(1280, True, id="wide")])
def test_a_folded_list_is_closed_on_a_phone_only(tree, tmp_path, width, open_):
    with opened(site.build(tree, draw=drawn), tmp_path, "projects/", width) as page:
        assert page.evaluate("document.querySelector('details.fold').open") is open_
