"""The layout check: opens every page of a built site in headless Chrome at phone widths and reports what breaks.

A page fails when it scrolls sideways, when an element sticks out past the right edge of the screen, when a block's text is
wider than the block (a table cell or card cell that overflows its box), when any visible text is under 12 pixels, when a bar
that stays on screen takes more than a fifth of its height, or when a link to a heading leaves the heading under such a bar. At
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

# Two portrait phones, a tablet and a phone held sideways: 360 and 390 are common Android and iPhone portrait widths, 768 is a
# small tablet, and 844 by 390 is an iPhone in landscape, where the height is what a bar that stays on screen eats into. The
# others are 800 tall.
HEIGHT = 800
VIEWPORTS = ((360, HEIGHT), (390, HEIGHT), (768, HEIGHT), (844, HEIGHT), (844, 390))
WIDTHS = tuple(width for width, _ in VIEWPORTS)
# A bar that stays on screen takes at most this share of the height.
MAX_BAR_SHARE = 0.2
MIN_FONT_PX = 12
# Subpixel rounding makes a box one pixel narrower than the text it holds.
TOLERANCE_PX = 1

MEASURE = """
([minFont, tolerance, maxBar]) => {
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
  for (const el of document.body.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if ((cs.position === 'sticky' || cs.position === 'fixed') && el.tagName !== 'DIALOG' && visible(el) && el.getBoundingClientRect().top <= 1) {
      const share = el.getBoundingClientRect().height / window.innerHeight;
      if (share > maxBar) problems.push(`${name(el)} stays on screen and takes ${Math.round(share * 100)}% of the ${window.innerHeight}px height`);
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


# The headings the page's own links name, each scrolled to as a link would: its top against the bar that stays on screen.
ANCHORS = """
(tolerance) => {
  const bar = (() => {
    let bottom = 0;
    for (const el of document.body.querySelectorAll('*')) {
      const cs = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      const stays = (cs.position === 'sticky' || cs.position === 'fixed') && el.tagName !== 'DIALOG';
      if (stays && el.getClientRects().length > 0 && rect.top <= 1 && rect.height < window.innerHeight / 2) bottom = Math.max(bottom, rect.bottom);
    }
    return bottom;
  })();
  const hidden = [];
  for (const link of document.querySelectorAll('a[href^="#"]')) {
    const id = decodeURIComponent(link.getAttribute('href').slice(1));
    const target = document.getElementById(id);
    if (!target) { hidden.push(`the link to #${id} names nothing on the page`); continue; }
    target.scrollIntoView();
    const top = target.getBoundingClientRect().top;
    if (top < bar - tolerance) hidden.push(`#${id} lands ${Math.round(bar - top)}px under the bar that stays on screen`);
  }
  window.scrollTo(0, 0);
  return [...new Set(hidden)];
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
    return page.evaluate(MEASURE, [MIN_FONT_PX, TOLERANCE_PX, MAX_BAR_SHARE])


def check_page(page: Page, url: str, viewport: tuple[int, int]) -> list[str]:
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    page.goto(url)
    page.wait_for_load_state("load")
    problems = measure(page) + page.evaluate(ANCHORS, TOLERANCE_PX)
    button = page.locator(".menu-btn")
    if button.is_visible():
        button.click()
        problems += [f"with the menu open, {problem}" for problem in measure(page)]
        if not page.locator("dialog.drawer").evaluate("el => el.open"):
            problems.append("the menu button does not open the menu")
        page.keyboard.press("Escape")
    return problems


def check(directory: Path, viewports: tuple[int | tuple[int, int], ...] = VIEWPORTS) -> list[str]:
    """Every layout problem on every page of the site in `directory`, each as `<page> at <width>px: <problem>`, or `<width>x<height>px`
    where the height is not the usual one. A bare width is that width at the usual height."""
    sizes = [(v, HEIGHT) if isinstance(v, int) else v for v in viewports]
    errors: list[str] = []
    pages = pages_of(directory)
    if not pages:
        return [f"{directory} has no pages"]
    with serving(directory) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            page = browser.new_page()
            for path in pages:
                for size in sizes:
                    label = f"{size[0]}px" if size[1] == HEIGHT else f"{size[0]}x{size[1]}px"
                    errors += [f"{path} at {label}: {problem}" for problem in check_page(page, base + path, size)]
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
        print(f"Layout ok: {len(pages_of(site))} pages at {', '.join(f'{w}x{h}' for w, h in VIEWPORTS)}px.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
