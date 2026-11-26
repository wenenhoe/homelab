"""A diagram that a screen shrinks can be shown at its own width, with no script."""

from __future__ import annotations

import shutil

import pytest
from doc_site import site
from doc_site.diagrams import Drawn
from test_page_style import opened

needs_chrome = pytest.mark.skipif(shutil.which("google-chrome") is None, reason="the pages are measured in the installed Google Chrome")


def svg(width: float) -> str:
    return f'<svg width="100%" style="max-width: {width}px;" viewBox="0 0 {width} 100"><rect width="{width}" height="100"/></svg>'


def build(tree, width: float) -> dict[str, bytes]:
    (tree / "docs/architecture/flow.md").write_text("# A flow\n\n```mermaid\nflowchart LR\n    a --> b\n```\n", encoding="utf-8")
    return site.build(tree, draw=lambda sources: [Drawn(svg(width), svg(width)) for _ in sources])


@pytest.mark.parametrize(("width", "boxed"), [pytest.param(900.4, True, id="wide"), pytest.param(300, False, id="always-fits")])
def test_only_a_diagram_a_screen_can_shrink_takes_the_box(tree, width, boxed):
    html = build(tree, width)["architecture/flow/index.html"].decode()
    assert ('<label class="zoom"><input type="checkbox"> Full size</label>' in html) is boxed
    assert ("--full:901px" in html) is boxed


@needs_chrome
def test_a_ticked_box_draws_the_diagram_at_its_own_width_and_the_page_does_not_scroll(tree, tmp_path):
    drawing = ".diagram .light svg"
    with opened(build(tree, 900), tmp_path, "architecture/flow/", 390) as page:
        assert page.locator(drawing).bounding_box()["width"] < 390
        page.locator(".diagram .zoom").click()
        assert page.locator(drawing).bounding_box()["width"] == 900
        assert page.evaluate("document.documentElement.scrollWidth") <= 390


@needs_chrome
@pytest.mark.parametrize(("width", "shown"), [pytest.param(390, True, id="shrunk"), pytest.param(1280, False, id="whole")])
def test_the_box_shows_only_where_the_diagram_is_shrunk(tree, tmp_path, width, shown):
    with opened(build(tree, 600), tmp_path, "architecture/flow/", width) as page:
        assert page.locator(".diagram .zoom").is_visible() is shown
