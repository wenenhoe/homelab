"""The rows of a generated view, before they are written down.

Each generated section is built as one of these blocks: a `Table` (headers, alignments and
the markdown source of every cell), a `Note` standing where an empty table would be, or
`Groups`, a heading over each of several tables. The markdown the views hold and the pages
the site publishes are both formatted from the same blocks, so what a view says has one
source. A cell holds markdown (a link, an inline code span, bold) with a `|` already escaped.
"""

from __future__ import annotations

from dataclasses import dataclass


def _line(cells: tuple[str, ...]) -> str:
    """One markdown row. A blank cell is a single space between its pipes, the compact form
    `.config/.markdownlint.yaml` accepts, not the two spaces a filled cell's padding leaves."""
    return "|" + "|".join(f" {cell} " if cell else " " for cell in cells) + "|"


@dataclass(frozen=True)
class Table:
    headers: tuple[str, ...]
    aligns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def markdown(self) -> str:
        return "\n".join([_line(self.headers), _line(self.aligns), *(_line(row) for row in self.rows)])


@dataclass(frozen=True)
class Note:
    text: str

    def markdown(self) -> str:
        return self.text


@dataclass(frozen=True)
class Groups:
    """A `### heading` over each table, in order."""

    items: tuple[tuple[str, Table], ...]

    def markdown(self) -> str:
        return "\n\n".join(f"### {heading}\n\n{table.markdown()}" for heading, table in self.items)


Block = Table | Note | Groups


@dataclass(frozen=True)
class Generated:
    """One generated section: the view file it belongs to, its `## heading`, and its rows."""

    view: str
    heading: str
    block: Block
