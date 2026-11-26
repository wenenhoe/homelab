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
