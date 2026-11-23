"""The counts at the top of a page: what a reader wants to know before reading a table, each linking to the section it counts.

A count is read from the rows of the section it names, so it cannot disagree with the table below it. A view without a count has no strip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from doc_scripts.view_model import Block, Grid, Table

# A project in a roadmap cell: a link whose text is its file name in code. A done project is not listed, so every link is a live one.
PROJECT_LINK = re.compile(r"\[`[^`]+`\]\(")
ROADMAP_COLUMNS = ("In progress", "Startable", "Waiting")


@dataclass(frozen=True)
class Tile:
    label: str
    value: int
    anchor: str  # the section it counts, by its id
    tone: str  # `ok`, `info`, `warn` or `mute`: the colour of the count
    note: str = ""  # a smaller line under the label


def _table(sections: dict[str, tuple[str, Block]], heading: str) -> tuple[str, Table | None]:
    """The section's anchor and its rows; no rows when the section holds a note, or is not there."""
    anchor, block = sections.get(heading, ("", None))
    return anchor, block if isinstance(block, Table) else None


def _rows(table: Table | None) -> int:
    return len(table.rows) if table else 0


def _numbers(sections: dict[str, tuple[str, Block]], heading: str) -> tuple[str, int]:
    """The section's anchor and how many numbers in its grid hold a decision, each counted once."""
    anchor, block = sections.get(heading, ("", None))
    return anchor, sum(cell.kind == "live" for _, cells in block.rows for cell in cells) if isinstance(block, Grid) else 0


def _approved(table: Table | None) -> int:
    """How many rows have a status that begins `Approved`: a decision settled and not yet built."""
    if not table or "Status" not in table.headers:
        return 0
    column = table.headers.index("Status")
    return sum(row[column].startswith("Approved") for row in table.rows)


def _projects(table: Table | None, column: str) -> int:
    if not table or column not in table.headers:
        return 0
    index = table.headers.index(column)
    return sum(len(PROJECT_LINK.findall(row[index])) for row in table.rows)


def _note(approved: int) -> str:
    return f"{approved} approved" if approved else ""


def tiles(slug: str, sections: dict[str, tuple[str, Block]]) -> list[Tile]:
    """The strip for the page `slug`. `sections` maps a heading to its anchor and rows."""
    if slug == "project-planning":
        roadmap_anchor, roadmap = _table(sections, "Roadmap")
        awaiting_anchor, awaiting = _table(sections, "Decisions awaiting a project")
        explorations_anchor, explorations = _table(sections, "Open explorations")
        approved = _approved(awaiting)
        return [
            Tile("In progress", _projects(roadmap, "In progress"), roadmap_anchor, "ok"),
            Tile("Startable", _projects(roadmap, "Startable"), roadmap_anchor, "info"),
            Tile("Waiting", _projects(roadmap, "Waiting"), roadmap_anchor, "mute"),
            Tile("Awaiting a project", _rows(awaiting), awaiting_anchor, "warn" if approved else "mute", _note(approved)),
            Tile("Open explorations", _rows(explorations), explorations_anchor, "mute"),
        ]
    if slug == "decision-index":
        number_anchor, numbers = _numbers(sections, "By number")
        open_anchor, open_decisions = _table(sections, "Open decisions")
        history_anchor, history = _table(sections, "History")
        approved = _approved(open_decisions)
        return [
            Tile("Decisions", numbers, number_anchor, "mute"),
            Tile("Open", _rows(open_decisions), open_anchor, "warn" if approved else "info", _note(approved)),
            Tile("Superseded or abandoned", _rows(history), history_anchor, "mute"),
        ]
    return []
