"""The small markdown subset the views are written in, as HTML, and the links between them.

A generated cell holds a link, an inline code span or bold text; a view's introduction holds
paragraphs of the same. Anything else is refused rather than shown wrongly, so a view that gains
a list or a code block fails the build until this module learns it.
"""

from __future__ import annotations

import html
import posixpath
import re
from collections.abc import Callable

REPO_URL = "https://github.com/wenenhoe/homelab"
SITE_URL = "https://wenenhoe.github.io/homelab/"
BRANCH = "main"

_TOKEN = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|\[(?P<text>(?:[^\[\]`]|`[^`]*`)+)\]\((?P<target>[^)\s]+)\)"
)
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
# What starts a block this module does not render: a list item, a quote, a fence, a table, a heading, markup, an indented line.
_UNSUPPORTED_BLOCK = re.compile(r"^(?:[-*+] |\d+[.)] |>|```|~~~|\||#|<|\s{4})")

Resolver = Callable[[str], str]


class UnsupportedMarkup(ValueError):
    """The text uses markdown the renderer does not handle."""


def github_slug(heading: str) -> str:
    """The anchor GitHub gives a heading: the lowercased text with everything but letters,
    digits, spaces, hyphens and underscores removed, then spaces as hyphens. Inline code and
    link markup count as their text."""
    text = re.sub(r"`([^`]*)`", r"\1", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


class Anchors:
    """Gives each heading on a page its anchor, numbering a repeat the way GitHub does."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def of(self, heading: str) -> str:
        slug = github_slug(heading)
        count = self._seen.get(slug, 0)
        self._seen[slug] = count + 1
        return slug if count == 0 else f"{slug}-{count}"


def inline(text: str, resolve: Resolver) -> str:
    """One cell or paragraph as HTML. `resolve` turns a link target into the address the page uses."""
    text = text.replace("\\|", "|")
    out: list[str] = []
    position = 0
    for match in _TOKEN.finditer(text):
        out.append(html.escape(text[position : match.start()], quote=False))
        if match["code"] is not None:
            out.append(f"<code>{html.escape(match['code'], quote=False)}</code>")
        elif match["bold"] is not None:
            out.append(f"<strong>{inline(match['bold'], resolve)}</strong>")
        else:
            out.append(f'<a href="{html.escape(resolve(match["target"]), quote=True)}">{inline(match["text"], resolve)}</a>')
        position = match.end()
    out.append(html.escape(text[position:], quote=False))
    return "".join(out)


def blocks(text: str) -> list[str]:
    """Blank-line separated paragraphs as markdown, each a single line. Refuses what starts a block this module does not render."""
    result = []
    for block in re.split(r"\n\s*\n", text.strip()):
        if not block.strip():
            continue
        for line in block.splitlines():
            if _UNSUPPORTED_BLOCK.match(line):
                raise UnsupportedMarkup(f"not rendered: {line.strip()[:60]!r}")
        result.append(" ".join(line.strip() for line in block.splitlines()))
    return result


def paragraphs(text: str, resolve: Resolver) -> list[str]:
    """Blank-line separated paragraphs as HTML. A wrapped paragraph is one line of text."""
    return [inline(block, resolve) for block in blocks(text)]


def link_resolver(view: str, pages: dict[str, str], is_dir: Callable[[str], bool]) -> Resolver:
    """The resolver for the view file `view`, a path from the repository root.

    A link to another view goes to its page, `pages` mapping a view's path to its address from
    the page being built; a link to any other file goes to it on GitHub, and one to a directory to the
    directory. An anchor is kept, so a link into a view reaches the same section on the site.
    """
    here = posixpath.dirname(view)

    def resolve(target: str) -> str:
        if _SCHEME.match(target) or target.startswith("#"):
            return target
        path, _, anchor = target.partition("#")
        full = posixpath.normpath(posixpath.join(here, path))
        if full.startswith(".."):
            raise UnsupportedMarkup(f"{view}: {target!r} leaves the repository")
        suffix = f"#{anchor}" if anchor else ""
        if full in pages:
            return pages[full] + suffix
        kind = "tree" if is_dir(full) else "blob"
        return f"{REPO_URL}/{kind}/{BRANCH}/{full}{suffix}"

    return resolve
