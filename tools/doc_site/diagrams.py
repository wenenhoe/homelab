"""Mermaid diagrams drawn to SVG during the build, so no script reaches a reader.

The bundle is the pinned file in `vendor/` (`mermaid.pin`, held by `vendor.py`). It runs in the installed Google Chrome, headless, in a
page that is made from nothing and cannot reach a network, and Mermaid's strict security level makes its own output safe to insert. Every
diagram is drawn twice, in Mermaid's light and dark themes, and the page shows the one the reader's system asks for. One browser draws
all of a build's diagrams, so the cost is the start of Chrome and the drawing itself, about ten seconds for the repository's diagrams.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from doc_site import vendor

BUNDLE = vendor.VENDOR / "mermaid.min.js"
THEMES = ("default", "dark")

DRAW = """
async ([theme, id, code]) => {
  const mermaid = __esbuild_esm_mermaid_nm.mermaid.default;
  mermaid.initialize({startOnLoad: false, securityLevel: 'strict', theme, suppressErrorRendering: true, handDrawnSeed: 1});
  try {
    return {svg: (await mermaid.render(id, code)).svg};
  } catch (error) {
    return {error: String(error && error.message || error)};
  }
}
"""


class DiagramError(ValueError):
    """A diagram Mermaid does not draw."""


@dataclass(frozen=True)
class Drawn:
    light: str
    dark: str


# What draws a build's diagrams: their sources in, one light and one dark SVG for each out.
Draw = Callable[[list[str]], list[Drawn]]


def skip(sources: list[str]) -> list[Drawn]:
    """Draws nothing, for what reads only the headings of a page."""
    return [Drawn("", "") for _ in sources]


def draw(sources: list[str], bundle: Path = BUNDLE) -> list[Drawn]:
    """Each source drawn in both themes. A diagram that fails raises `DiagramError` naming its position in `sources`."""
    if not sources:
        return []
    errors = vendor.local_errors(pin_path=vendor.MERMAID_PIN)
    if errors:
        raise DiagramError(errors[0])
    from playwright.sync_api import sync_playwright  # imported here: a build with no diagram needs no browser

    drawn: list[Drawn] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            page = browser.new_page(java_script_enabled=True)
            page.route("**/*", lambda route: route.abort())
            page.set_content("<!doctype html><html><body></body></html>")
            page.add_script_tag(content=bundle.read_text(encoding="utf-8"))
            for index, source in enumerate(sources):
                svgs = []
                for theme, name in zip(THEMES, ("light", "dark"), strict=True):
                    result = page.evaluate(DRAW, [theme, f"mmd-{index}-{name}", source])
                    if "error" in result:
                        raise DiagramError(f"diagram {index}: {result['error']}")
                    svgs.append(result["svg"])
                drawn.append(Drawn(*svgs))
        finally:
            browser.close()
    return drawn
