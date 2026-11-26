"""The layout check: opens every page of a built site in headless Chrome at phone widths, and at wide ones where a page has a
contents list or tabs, and reports what breaks.

A page fails when it scrolls sideways, when an element sticks out past the right edge of the screen, when a block's text is
wider than the block (a table cell or card cell that overflows its box), when any visible text is under 12 pixels, when a bar
that stays on screen takes more than a fifth of its height, or when a link to a heading leaves the heading under such a bar. At
widths where the page has a menu drawer the drawer is opened and held to the same rules. The check serves the directory
over localhost and uses the Chrome that is installed (`channel="chrome"`), so nothing is downloaded. A page is loaded once and
resized to each width, and the pages are shared among a few browsers that run side by side.

Usage (from tools/): python -m doc_site.layout [--sample] SITE_DIR

`--sample` opens a fixed set of pages instead of all of them: the home page, every view and section landing, one page of each section
and the longest page with a contents list. The set does not grow with the number of pages, so a pull request's run takes a bounded time.
`--changed FILE` names the paths a change touches, one to a line: the sample then also opens the page of each document among them, and
every page is opened when one is under `tools/doc_site/`, since the renderer shapes them all.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import multiprocessing
import sys
import threading
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from doc_site import chrome

# Two portrait phones, a tablet and a phone held sideways: 360 and 390 are common Android and iPhone portrait widths, 768 is a
# small tablet, and 844 by 390 is an iPhone in landscape, where the height is what a bar that stays on screen eats into. The
# others are 800 tall.
HEIGHT = 800
VIEWPORTS = ((360, HEIGHT), (390, HEIGHT), (768, HEIGHT), (844, HEIGHT), (844, 390))
WIDTHS = tuple(width for width, _ in VIEWPORTS)
# A page that lists its headings beside its prose, or shows groups as tabs, is also opened where the list has a column of its own: at the
# narrowest such width (the stylesheet's breakpoint), where the prose has the least room, and at a usual desktop one.
WIDE_VIEWPORTS = ((1040, HEIGHT), (1280, HEIGHT))
# The sections of the site that hold document pages, by the first part of their address.
SECTIONS = ("projects", "decisions", "topics", "architecture")
# The most pages `sample_of` may return, however many the site has: the home page, the views and the landings, a page of each section
# and a long one, with room for a view or two. A test holds the sample to it.
MAX_SAMPLE = 16
# A change under this directory can break any page, so it is checked against all of them.
RENDERER = "tools/doc_site/"
# What marks such a page.
ORIENTED = "() => document.querySelector('nav.toc, .tabs') !== null"
# Two frames: a change of width reaches a script's media query listener on the next one, before the page is measured.
SETTLED = "() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"
# Browsers that run side by side. A browser spends most of a check waiting on the driver, so more than the cores a runner has still helps.
WORKERS = 4
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
  const seen = new Map();
  const clipped = (el) => {
    if (!el) return false;
    if (seen.has(el)) return seen.get(el);
    const cs = getComputedStyle(el);
    const hidden = (cs.position === 'absolute' && el.clientWidth <= 1 && el.clientHeight <= 1)
      || /rect\\(0(px)?, 0(px)?, 0(px)?, 0(px)?\\)/.test(cs.clip)
      || clipped(el.parentElement);
    seen.set(el, hidden);
    return hidden;
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
    // A tab's panel is shown by the address alone, so a heading in one is reached the way its link reaches it.
    if (target.getClientRects().length === 0) location.hash = id;
    target.scrollIntoView();
    const top = target.getBoundingClientRect().top;
    if (top < bar - tolerance) hidden.push(`#${id} lands ${Math.round(bar - top)}px under the bar that stays on screen`);
  }
  if (location.hash) location.replace(location.pathname + '#');
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


def page_of_document(path: str) -> str | None:
    """The address of the page of the repository file `path`, or None when it is not a markdown file under `docs/`. A README is the page
    of its directory and the README of `docs/` is the home page, as in `doc_site.site`."""
    if not (path.startswith("docs/") and path.endswith(".md")):
        return None
    slug = path.removeprefix("docs/").removesuffix(".md")
    slug = "" if slug == "README" else slug.removesuffix("/README")
    return f"/{slug}/" if slug else "/"


def sample_of(directory: Path, changed: Sequence[str] = ()) -> list[str]:
    """A fixed set of the pages of the site in `directory`, in the order of `pages_of`: the home page, every page one directory deep (the
    views and the landings of the sections, the Topics index among them), the first page in each section, and the page with a contents
    list that has the most markup, which is the longest document, and the page of each document in `changed`, the paths a change touches,
    that has one. Every kind of page is in it once at least, and its size does not depend on how many pages the site has, only on how many
    the change names."""
    pages = pages_of(directory)
    chosen = {path for path in pages if path.count("/") <= 2}
    for section in SECTIONS:
        chosen.update([path for path in pages if path.startswith(f"/{section}/") and path.count("/") > 2][:1])
    long = [path for path in pages if 'class="toc"' in (directory / path.strip("/") / "index.html").read_text(encoding="utf-8")]
    if long:
        chosen.add(max(long, key=lambda path: ((directory / path.strip("/") / "index.html").stat().st_size, path)))
    chosen.update(path for path in map(page_of_document, changed) if path in pages)
    return [path for path in pages if path in chosen]


def measure(page: Page) -> list[str]:
    return page.evaluate(MEASURE, [MIN_FONT_PX, TOLERANCE_PX, MAX_BAR_SHARE])


MENU_OPEN = "() => { const d = document.querySelector('dialog.drawer'); return d !== null && d.open; }"
MENU_SHOWN = """() => {
  const b = document.querySelector('.menu-btn');
  return b !== null && b.getClientRects().length > 0 && getComputedStyle(b).visibility !== 'hidden';
}"""


def check_page(page: Page, url: str, sizes: Sequence[tuple[int, int]], wide: Sequence[tuple[int, int]] = ()) -> list[tuple[int, str]]:
    """The problems of the page at `url` at each of `sizes`, as (index of the size, problem), and at each of `wide` after them, their
    indexes following on, when the page lists its headings or shows tabs. The page is loaded once and resized, since nothing in it depends on the
    width at load time."""
    problems: list[tuple[int, str]] = []
    page.set_viewport_size({"width": sizes[0][0], "height": sizes[0][1]})
    page.goto(url)
    page.wait_for_load_state("load")
    sizes = [*sizes, *wide] if wide and page.evaluate(ORIENTED) else list(sizes)
    for index, (width, height) in enumerate(sizes):
        if index:
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate(SETTLED)
        found = measure(page) + page.evaluate(ANCHORS, TOLERANCE_PX)
        if page.evaluate(MENU_SHOWN):
            page.locator(".menu-btn").click()
            found += [f"with the menu open, {problem}" for problem in measure(page)]
            if not page.evaluate(MENU_OPEN):
                found.append("the menu button does not open the menu")
            page.keyboard.press("Escape")
        problems += [(index, problem) for problem in found]
    return problems


def _check_chunk(base: str, paths: Sequence[str], sizes: Sequence[tuple[int, int]], wide: Sequence[tuple[int, int]]) -> list[tuple[str, int, str]]:
    """The problems of `paths` as (path, index of the size, problem), in one browser of its own."""
    found: list[tuple[str, int, str]] = []
    with sync_playwright() as playwright:
        browser = chrome.launch(playwright)
        try:
            page = browser.new_page()
            for path in paths:
                found += [(path, index, problem) for index, problem in check_page(page, base + path, sizes, wide)]
        finally:
            browser.close()
    return found


def check(
    directory: Path,
    viewports: tuple[int | tuple[int, int], ...] = VIEWPORTS,
    workers: int = WORKERS,
    wide: Sequence[tuple[int, int]] = WIDE_VIEWPORTS,
    pages: Sequence[str] | None = None,
) -> list[str]:
    """Every layout problem on every page of the site in `directory`, each as `<page> at <width>px: <problem>`, or `<width>x<height>px`
    where the height is not the usual one, in the order of the pages and then of `viewports`, then of `wide` for a page that lists its headings
    or shows tabs. A bare width is that width at the usual height. `pages` names the ones to open, as `pages_of` does, and is every page
    by default. The pages are dealt out to up to `workers` browsers."""
    sizes = [(v, HEIGHT) if isinstance(v, int) else v for v in viewports]
    pages = list(pages) if pages is not None else pages_of(directory)
    if not pages:
        return [f"{directory} has no pages"]
    chunks = [pages[i::workers] for i in range(min(workers, len(pages)))]
    with serving(directory) as base:
        if len(chunks) == 1:
            found = _check_chunk(base, chunks[0], sizes, wide)
        else:
            # `spawn`, since the server above runs a thread and a forked child would inherit it halfway through a request.
            with ProcessPoolExecutor(len(chunks), mp_context=multiprocessing.get_context("spawn")) as pool:
                found = [item for chunk in pool.map(_check_chunk, [base] * len(chunks), chunks, [sizes] * len(chunks), [wide] * len(chunks)) for item in chunk]
    order = {path: n for n, path in enumerate(pages)}
    found.sort(key=lambda item: (order[item[0]], item[1]))
    labels = [f"{w}px" if h == HEIGHT else f"{w}x{h}px" for w, h in [*sizes, *wide]]
    return [f"{path} at {labels[index]}: {problem}" for path, index, problem in found]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site", type=Path, help="a built site's directory")
    parser.add_argument("--sample", action="store_true", help="open a fixed set of pages instead of every page")
    parser.add_argument("--changed", type=Path, help="with --sample, a file of the paths a change touches, one to a line")
    args = parser.parse_args(argv)
    if args.changed and not args.sample:
        parser.error("--changed goes with --sample")
    changed = args.changed.read_text(encoding="utf-8").splitlines() if args.changed else []
    everything = not args.sample or any(path.startswith(RENDERER) for path in changed)
    pages = pages_of(args.site) if everything else sample_of(args.site, changed)
    errors = check(args.site, pages=pages)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if not errors:
        phones = ", ".join(f"{w}x{h}" for w, h in VIEWPORTS)
        wide = ", ".join(f"{w}x{h}" for w, h in WIDE_VIEWPORTS)
        which = f"{len(pages)} pages" if everything else f"{len(pages)} of {len(pages_of(args.site))} pages"
        print(f"Layout ok: {which} at {phones}px, and at {wide}px where a page has a list or tabs.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
