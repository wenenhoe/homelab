"""A markdown document of the repository as HTML: its body, its headings and its title.

A CommonMark library reads the body, so lists, tables, code blocks and the rest come out as GitHub's rules say. What the repository's
documents use is a small set, and anything else is refused rather than shown wrongly, as `markup.py` does for the views: raw HTML,
an image, a block the renderer has no rule for. A Mermaid block is left as a marker, which the build replaces with the diagram
(`diagrams.py`). A heading takes the anchor GitHub gives it, a link is turned into the address the page
uses, a task-list item is a box, and a table carries the labels its cells need for the card layout on a phone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.token import Token

from doc_site.markup import Anchors, Heading, Resolver, UnsupportedMarkup, status_key

# The token types of the blocks and spans the repository's documents are written in.
BLOCKS = frozenset(
    {
        "paragraph_open", "paragraph_close", "inline", "heading_open", "heading_close",
        "bullet_list_open", "bullet_list_close", "ordered_list_open", "ordered_list_close", "list_item_open", "list_item_close",
        "blockquote_open", "blockquote_close", "fence", "code_block", "hr",
        "table_open", "table_close", "thead_open", "thead_close", "tbody_open", "tbody_close",
        "tr_open", "tr_close", "th_open", "th_close", "td_open", "td_close",
    }
)  # fmt: skip
SPANS = frozenset(
    {"text", "code_inline", "strong_open", "strong_close", "em_open", "em_close", "s_open", "s_close", "link_open", "link_close", "softbreak", "hardbreak"}
)
COMMENT = re.compile(r"\s*<!--.*?-->\s*", re.DOTALL)
FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
TASK = re.compile(r"\[( |x|X)\] ")
CHECKBOX = '<input type="checkbox" disabled aria-label="{label}"{checked}> '


MARKER = "<!--diagram:{}-->"


@dataclass(frozen=True)
class Diagram:
    line: int  # where its fence opens in the file
    code: str


@dataclass(frozen=True)
class Rendered:
    title: str  # the text of the `# ` heading, which the page shows itself
    title_id: str
    html: str  # the rest of the body; a Mermaid block is a `MARKER` for the diagram of that number, for the build to replace
    headings: tuple[Heading, ...]  # the `##` and `###` headings, for the page's contents
    diagrams: tuple[Diagram, ...] = ()


def _plain(inline: Token) -> str:
    return "".join(child.content for child in inline.children or [] if child.type in ("text", "code_inline"))


def _where(source: str, token: Token) -> str:
    return f"{source}:{token.map[0] + 1}" if token.map else source


def _refuse(source: str, token: Token, what: str) -> UnsupportedMarkup:
    return UnsupportedMarkup(f"{_where(source, token)}: {what} is not rendered")


def _checked(source: str, tokens: list[Token]) -> list[Token]:
    """`tokens` without the HTML comments, which GitHub does not show either; raises for what no rule covers."""
    kept = []
    for token in tokens:
        if token.type == "html_block":
            if not COMMENT.fullmatch(token.content):
                raise _refuse(source, token, f"HTML {token.content.strip()[:40]!r}")
            continue
        if token.type not in BLOCKS:
            raise _refuse(source, token, f"a block of type {token.type!r}")
        if token.type == "inline":
            children = []
            for child in token.children or []:
                if child.type == "html_inline" and COMMENT.fullmatch(child.content):
                    continue
                if child.type not in SPANS:
                    raise _refuse(source, token, f"{'an image' if child.type == 'image' else f'markup of type {child.type!r}'}")
                children.append(child)
            token.children = children
        kept.append(token)
    return kept


def _html(content: str) -> Token:
    token = Token("html_inline", "", 0)
    token.content = content
    return token


def _html_block(content: str) -> Token:
    token = Token("html_block", "", 0)
    token.content = content + "\n"
    return token


def _tasks(tokens: list[Token]) -> None:
    """A list item that opens with `[ ]` or `[x]` is a box, and its list drops the bullets."""
    lists: list[Token] = []
    for index, token in enumerate(tokens):
        if token.type in ("bullet_list_open", "ordered_list_open"):
            lists.append(token)
        elif token.type in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
        elif token.type == "list_item_open" and tokens[index + 1].type == "paragraph_open" and tokens[index + 2].type == "inline":
            inline = tokens[index + 2]
            first = inline.children[0] if inline.children else None
            found = TASK.match(first.content) if first is not None and first.type == "text" else None
            if found:
                first.content = first.content[found.end() :]
                done = found[1] != " "
                inline.children.insert(0, _html(CHECKBOX.format(label="done" if done else "not done", checked=" checked" if done else "")))
                token.attrSet("class", "task")
                lists[-1].attrSet("class", "tasks")


# A word of code in a key cell is kept whole only while that leaves its table room in the column: not beyond this many columns, where the
# others need the width, nor beyond this many characters, as a request's path with its query has.
MAX_WHOLE_COLUMNS = 3
MAX_WHOLE_WORD = 40


def _may_cut(inline: Token, columns: int) -> bool:
    words = (word for child in inline.children or [] if child.type == "code_inline" for word in child.content.split())
    return columns > MAX_WHOLE_COLUMNS or any(len(word) > MAX_WHOLE_WORD for word in words)


def _tables(tokens: list[Token]) -> None:
    """Each cell takes its column's header as a label and a `Status` cell is a pill, as in the views, so a wide table becomes cards. The
    first cell of a row is its `key`, unless the table has one column or its first is `#`, which numbers the rows and does not name them."""
    labels: list[str] = []
    column = 0
    for index, token in enumerate(tokens):
        if token.type == "tr_open":
            column = 0
        elif token.type == "th_open":
            labels.append(_plain(tokens[index + 1]))
        if token.type in ("th_open", "td_open"):
            token.attrs.pop("style", None)
            if token.type == "td_open":
                label = labels[column] if column < len(labels) else ""
                inline = tokens[index + 1]
                empty = not inline.content.strip()
                token.attrSet("data-label", label)
                keyed = column == 0 and len(labels) > 1 and labels[0] != "#"
                kind = "none" if empty else ("key cut" if _may_cut(inline, len(labels)) else "key") if keyed else ""
                token.attrSet("class", f"field {kind}".strip())
                if label == "Status" and not empty:
                    inline.children.insert(0, _html(f'<span class="pill s-{status_key(inline.content)}">'))
                    inline.children.append(_html("</span>"))
            column += 1
        elif token.type == "table_open":
            labels.clear()


def render(text: str, resolve: Resolver, source: str = "document") -> Rendered:
    """The body of the markdown file `text` (its front matter is left off) as HTML. `source` names it in an error."""
    md = MarkdownIt("commonmark").enable(["table", "strikethrough"])
    # The front matter becomes blank lines, so a line number in an error is the line of the file.
    tokens = _checked(source, md.parse(FRONT_MATTER.sub(lambda found: "\n" * found[0].count("\n"), text, count=1)))
    anchors = Anchors()
    headings: list[Heading] = []
    title = title_id = ""
    body: list[Token] = []
    diagrams: list[Diagram] = []
    skip = 0
    for index, token in enumerate(tokens):
        if skip:
            skip -= 1
            continue
        if token.type == "heading_open":
            inline = tokens[index + 1]
            level = int(token.tag[1])
            anchor = anchors.of(inline.content)
            if level == 1 and not title:
                title, title_id, skip = _plain(inline), anchor, 2
                continue
            token.attrSet("id", anchor)
            if level in (2, 3):
                headings.append(Heading(level, anchor, _plain(inline)))
        if token.type == "fence" and token.info.split()[:1] == ["mermaid"]:
            token = _html_block(MARKER.format(len(diagrams)))
            diagrams.append(Diagram((tokens[index].map or [0])[0] + 1, tokens[index].content))
        if token.type == "inline":
            for child in token.children:
                if child.type == "link_open":
                    child.attrSet("href", resolve(child.attrGet("href") or ""))
        body.append(token)
    if not title:
        raise UnsupportedMarkup(f"{source} has no `# ` title")
    _tasks(body)
    _tables(body)
    return Rendered(title, title_id, md.renderer.render(body, md.options, {}), tuple(headings), tuple(diagrams))
