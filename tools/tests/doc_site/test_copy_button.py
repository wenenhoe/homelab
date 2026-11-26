"""The copy button the script adds to each code block of a document page, driven in the installed Chrome."""

from __future__ import annotations

import shutil
from collections.abc import Iterator

import pytest
from doc_site import layout, site

sync_api = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.skipif(shutil.which("google-chrome") is None, reason="drives the installed Google Chrome")

BLOCK = "# [1/2] first line\nssh security\n    indented <not markup> & kept"
DOCUMENT = f"# The network\n\n```sh\n{BLOCK}\n```\n\n- a step:\n\n  ```sh\n  second\n  ```\n"
PAGE = "/topics/infra/network/"


@pytest.fixture
def base(tree, tmp_path) -> Iterator[str]:
    (tree / "docs/topics/infra/network.md").write_text(DOCUMENT, encoding="utf-8")
    out = tmp_path / "site"
    site.write(out, tree)
    with layout.serving(out) as url:
        yield url


@pytest.fixture
def browser() -> Iterator[object]:
    with sync_api.sync_playwright() as playwright:
        chrome = playwright.chromium.launch(channel="chrome")
        try:
            yield chrome
        finally:
            chrome.close()


def open_page(browser, base: str, setup: str = ""):
    context = browser.new_context()
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    if setup:
        context.add_init_script(setup)
    page = context.new_page()
    page.goto(base + PAGE)
    return page


def clipboard(page) -> str:
    return page.evaluate("navigator.clipboard.readText()")


def test_a_button_copies_its_own_block_without_the_final_newline(base, browser):
    page = open_page(browser, base)
    first, second = page.locator("button.copy").all()
    idle = first.inner_html()

    first.click()
    sync_api.expect(first).to_have_text("Copied")
    assert first.locator("svg").inner_html() not in idle
    assert clipboard(page) == BLOCK

    second.click()
    sync_api.expect(second).to_have_text("Copied")
    assert clipboard(page) == "second"
    sync_api.expect(second).to_have_text("Copy")


def test_the_button_is_in_the_top_right_corner_clear_of_the_text(base, browser):
    page = open_page(browser, base)
    block = page.locator(".doc pre").first.bounding_box()
    button = page.locator("button.copy").first.bounding_box()
    text_right = page.locator(".doc pre").first.evaluate("e => e.getBoundingClientRect().right - parseFloat(getComputedStyle(e).paddingRight)")

    assert (button["width"], button["height"]) == (44, 44)
    assert 0 < block["x"] + block["width"] - (button["x"] + button["width"]) < 8
    assert 0 < button["y"] - block["y"] < 8
    assert button["y"] + button["height"] < block["y"] + block["height"]
    assert text_right <= button["x"]


def test_a_refused_write_is_said(base, browser):
    page = open_page(browser, base, "navigator.clipboard.writeText = () => Promise.reject(new Error('refused'));")
    button = page.locator("button.copy").first

    button.click()

    sync_api.expect(button).to_have_text("Copy failed")


def test_without_a_clipboard_the_blocks_are_left_as_built(base, browser):
    page = open_page(browser, base, "Object.defineProperty(Navigator.prototype, 'clipboard', { get: () => undefined });")

    assert page.locator("button.copy").count() == 0
    assert page.locator(".doc pre").count() == 2
