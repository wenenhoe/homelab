"""The layout check: opens every page of a built site in headless Chrome at phone widths and reports what breaks.

A page fails when it scrolls sideways, when an element sticks out past the right edge of the screen, when a block's text is
wider than the block (a table cell or card cell that overflows its box), or when any visible text is under 12 pixels. At
widths where the page has a menu drawer the drawer is opened and held to the same rules. The check serves the directory
over localhost and uses the Chrome that is installed (`channel="chrome"`), so nothing is downloaded.

Usage (from tools/): python -m doc_site.layout SITE_DIR
"""

from __future__ import annotations

import argparse
import functools
import http.server
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

# Two portrait and two landscape phones, and a tablet in between: 360 and 390 are common Android and iPhone portrait widths,
# 844 is the iPhone landscape width, 768 a small tablet.
WIDTHS = (360, 390, 768, 844)
HEIGHT = 800
MIN_FONT_PX = 12
# Subpixel rounding makes a box one pixel narrower than the text it holds.
TOLERANCE_PX = 1

MEASURE = """
([minFont, tolerance]) => {
  const problems = [];
  const name = (el) => {
    const classes = typeof el.className === 'string' ? el.className.trim().split(/\\s+/).filter(Boolean) : [];
    return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + classes.map((c) => '.' + c).join('');
  };
  // Text hidden the screen-reader way (a 1px clipped box) is not on the screen, so it is not measured.
  const clipped = (el) => {
    for (let a = el; a; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.position === 'absolute' && a.clientWidth <= 1 && a.clientHeight <= 1) return true;
      if (/rect\\(0(px)?, 0(px)?, 0(px)?, 0(px)?\\)/.test(cs.clip)) return true;
    }
    return false;
  };
  const visible = (el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden' && !clipped(el);
  const root = document.documentElement;
  if (root.scrollWidth > root.clientWidth + tolerance) {
    problems.push(`the page scrolls sideways (${root.scrollWidth}px of content in ${root.clientWidth}px)`);
  }
  for (const el of document.body.querySelectorAll('*')) {
    if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName) || !visible(el)) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width > 0 && rect.right > root.clientWidth + tolerance) {
      problems.push(`${name(el)} ends at ${Math.round(rect.right)}px, past the ${root.clientWidth}px screen`);
    }
    if (el.clientWidth > 0 && el.scrollWidth > el.clientWidth + tolerance && getComputedStyle(el).display !== 'inline') {
      problems.push(`${name(el)} holds ${el.scrollWidth}px of content in a ${el.clientWidth}px box`);
    }
  }
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const small = new Set();
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const parent = node.parentElement;
    if (!node.textContent.trim() || !parent || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(parent.tagName) || !visible(parent)) continue;
    const size = parseFloat(getComputedStyle(parent).fontSize);
    if (size < minFont) small.add(`${name(parent)} has ${size}px text`);
  }
  problems.push(...small);
  return [...new Set(problems)];
}
"""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def serving(directory: Path) -> Iterator[str]:
    """`directory` served on a free localhost port; yields the base URL."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def pages_of(directory: Path) -> list[str]:
    """The URL path of every HTML page under `directory`, sorted: `/` for the home page, `/<dir>/` for the others."""
    paths = []
    for page in directory.rglob("index.html"):
        relative = page.parent.relative_to(directory).as_posix()
        paths.append("/" if relative == "." else f"/{relative}/")
    return sorted(paths)


def measure(page: Page) -> list[str]:
    return page.evaluate(MEASURE, [MIN_FONT_PX, TOLERANCE_PX])


def check_page(page: Page, url: str, width: int) -> list[str]:
    page.set_viewport_size({"width": width, "height": HEIGHT})
    page.goto(url)
    page.wait_for_load_state("load")
    problems = measure(page)
    button = page.locator(".menu-btn")
    if button.is_visible():
        button.click()
        problems += [f"with the menu open, {problem}" for problem in measure(page)]
        if not page.locator("dialog.drawer").evaluate("el => el.open"):
            problems.append("the menu button does not open the menu")
        page.keyboard.press("Escape")
    return problems


def check(directory: Path, widths: tuple[int, ...] = WIDTHS) -> list[str]:
    """Every layout problem on every page of the site in `directory`, each as `<page> at <width>px: <problem>`."""
    errors: list[str] = []
    pages = pages_of(directory)
    if not pages:
        return [f"{directory} has no pages"]
    with serving(directory) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            page = browser.new_page()
            for path in pages:
                for width in widths:
                    errors += [f"{path} at {width}px: {problem}" for problem in check_page(page, base + path, width)]
        finally:
            browser.close()
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site", type=Path, help="a built site's directory")
    site = parser.parse_args(argv).site
    errors = check(site)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if not errors:
        print(f"Layout ok: {len(pages_of(site))} pages at {', '.join(map(str, WIDTHS))}px.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
