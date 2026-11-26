"""The home page's markdown: a template whose slots are filled from the repository's `README.md`, so the page shows what the README
says without a second copy of it.

The template holds the page's title, what only the site says, and a line for each part of the README it shows: `<!-- readme -->` for
the text before the first `##` section, without its title and badges, and `<!-- readme: <anchor> -->` for the `##` section with that
anchor, heading and all. A slot that names no section fails the build, so a renamed heading cannot drop a part of the page unseen.
"""

from __future__ import annotations

import re
from pathlib import Path

from markdown_it import MarkdownIt

from doc_site.markup import UnsupportedMarkup, github_slug

TEMPLATE = "tools/doc_scripts/view_intros/home.md"
README = "README.md"

SLOT = re.compile(r"^<!-- readme(?:: (?P<anchor>[\w-]+))? -->$", re.MULTILINE)
_SCHEME = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#)", re.IGNORECASE)
# An image, alone or as the text of a link: what a badge is written as. The renderer shows no image.
_IMAGE = r"!\[[^\]]*\]\([^)]*\)"
_BADGES = re.compile(rf"(?:(?:\[{_IMAGE}\]\([^)]*\)|{_IMAGE})\s*)+")


def _parts(readme: str) -> dict[str, str]:
    """The README by slot: `""` for what precedes the first `##` section, then each section by its anchor. Headings are found by the
    parser, so a `##` line in a code block starts no section."""
    tokens = MarkdownIt("commonmark").enable("table").parse(readme)
    lines = readme.splitlines()
    heads = [(token.map[0], int(token.tag[1]), tokens[index + 1].content) for index, token in enumerate(tokens) if token.type == "heading_open"]
    title = next((line for line, level, _ in heads if level == 1), -1)
    sections = [(line, github_slug(text)) for line, level, text in heads if level == 2]
    ends = [line for line, _ in sections] + [len(lines)]
    opening = "\n".join(lines[title + 1 : ends[0]])
    parts = {"": "\n\n".join(block for block in re.split(r"\n\s*\n", opening.strip()) if not _BADGES.fullmatch(block.strip()))}
    for (start, anchor), end in zip(sections, ends[1:], strict=True):
        parts[anchor] = "\n".join(lines[start:end]).strip()
    return parts


def _refuse_relative_links(template: str) -> None:
    """The filled page's links are read from the repository's root, as the README's are, so a relative link written in the template
    would be read from there while the file it is in sits elsewhere."""
    for token in MarkdownIt("commonmark").parse(template):
        for child in token.children or []:
            if child.type == "link_open" and not _SCHEME.match(child.attrGet("href") or ""):
                raise UnsupportedMarkup(f"{TEMPLATE}: {child.attrGet('href')!r} is a relative link; write the full address")


def markdown(root: Path) -> str:
    """The home page of the tree at `root` as markdown, its links relative to `root`."""
    template = (root / TEMPLATE).read_text(encoding="utf-8")
    _refuse_relative_links(template)
    parts = _parts((root / README).read_text(encoding="utf-8"))

    def fill(slot: re.Match) -> str:
        anchor = slot["anchor"] or ""
        if anchor not in parts:
            raise UnsupportedMarkup(f"{TEMPLATE}: {README} has no `##` section with the anchor {anchor!r}")
        return parts[anchor]

    return SLOT.sub(fill, template)
