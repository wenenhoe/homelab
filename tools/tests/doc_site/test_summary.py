"""The counts at the top of a page are read from the rows of the section they link to."""

from __future__ import annotations

import re

from doc_scripts.view_model import Grid, GridCell, Note, Table
from doc_site import site
from doc_site.summary import Tile, tiles

ROADMAP = Table(
    ("Initiative", "In progress", "Startable", "Waiting"),
    (":---",) * 4,
    (
        ("`a`", "[`one.md`](projects/one.md) (unblocks 2), [`two.md`](projects/two.md)", "—", "[`three.md`](projects/three.md)"),
        ("`b`", "—", "[`four.md`](projects/four.md)", "—"),
    ),
)
AWAITING = Table(
    ("ADR", "Decision", "Problem", "Current solution", "Status"), (":---",) * 5, (("1", "t", "p", "s", "Approved (000)"), ("2", "t", "p", "s", "Working"))
)


def sections(**blocks):
    return {heading: (heading.lower().replace(" ", "-"), block) for heading, block in blocks.items()}


def test_projects_are_counted_in_each_roadmap_column_and_a_dash_is_none():
    strip = {tile.label: tile.value for tile in tiles("project-planning", sections(Roadmap=ROADMAP))}
    assert (strip["In progress"], strip["Startable"], strip["Waiting"]) == (2, 1, 1)


def test_an_unblocks_count_is_not_a_project():
    cell = "[`one.md`](projects/one.md) (unblocks 2)"
    table = Table(("Initiative", "In progress"), (":---",) * 2, (("`a`", cell),))
    assert tiles("project-planning", sections(Roadmap=table))[0].value == 1


def test_decisions_awaiting_a_project_say_how_many_are_approved():
    tile = next(t for t in tiles("project-planning", sections(**{"Decisions awaiting a project": AWAITING})) if t.label == "Awaiting a project")
    assert (tile.value, tile.note, tile.tone) == (2, "1 approved", "warn")


def test_nothing_approved_is_quiet():
    table = Table(AWAITING.headers, AWAITING.aligns, AWAITING.rows[1:])
    tile = next(t for t in tiles("project-planning", sections(**{"Decisions awaiting a project": table})) if t.label == "Awaiting a project")
    assert (tile.value, tile.note, tile.tone) == (1, "", "mute")


def test_a_section_that_holds_a_note_counts_nothing():
    strip = tiles("project-planning", sections(**{"Open explorations": Note("None.")}))
    assert next(t for t in strip if t.label == "Open explorations").value == 0


def test_a_section_the_page_lacks_counts_nothing_and_links_nowhere():
    assert Tile("In progress", 0, "", "ok") == tiles("project-planning", {})[0]


def test_the_decision_index_counts_its_tables():
    open_decisions = Table(
        ("ADR", "Revision", "Decision", "Status", "Implemented by"), (":---",) * 5, (("1", "0", "d", "Approved", "—"), ("2", "0", "d", "Working", "—"))
    )
    history = Table(("ADR", "Revision", "Decision", "Status", "Replaced by"), (":---",) * 5, (("3", "0", "d", "Superseded", "1"),))
    cells = (
        *(GridCell(str(n), "live") for n in range(1, 6)),
        GridCell("6 \u2192 1", "merged"),
        GridCell("\u2014", "gap"),
        *(GridCell("", "none") for _ in range(3)),
    )
    by_number = Grid(10, (("000x", cells),))
    strip = {t.label: t for t in tiles("decision-index", sections(**{"By number": by_number, "Open decisions": open_decisions, "History": history}))}
    assert (strip["Decisions"].value, strip["Open"].value, strip["Open"].note, strip["Superseded or abandoned"].value) == (5, 2, "1 approved", 1)


def test_a_view_with_no_counts_has_no_strip():
    assert tiles("dr-coverage", {}) == []


def test_the_page_shows_each_count_linked_to_its_section(tree):
    html = site.build(tree)["project-planning/index.html"].decode()
    strip = html[html.index('<nav class="stats"') : html.index("</nav>", html.index('<nav class="stats"'))]
    assert re.findall(r'href="#([^"]+)"><strong>(\d+)</strong><span>([^<]+)</span>', strip) == [
        ("roadmap", "1", "In progress"),
        ("roadmap", "1", "Startable"),
        ("roadmap", "0", "Waiting"),
        ("decisions-awaiting-a-project", "1", "Awaiting a project"),
        ("open-explorations", "0", "Open explorations"),
    ]
    assert all(f'id="{anchor}"' in html for anchor in re.findall(r'class="stat [^"]*" href="#([^"]+)"', strip))


def test_a_page_without_counts_has_no_strip(tree):
    assert "stats" not in site.build(tree)["dr-coverage/index.html"].decode().split("<main>")[1]
