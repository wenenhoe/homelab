"""The row model: the markdown it writes is what the views have always held."""

from __future__ import annotations

from doc_scripts.view_model import Groups, Note, Table


def test_a_table_writes_its_header_alignment_and_rows():
    table = Table(("A", "B"), (":---", "---:"), (("x", "y"),))
    assert table.markdown() == "| A | B |\n| :--- | ---: |\n| x | y |"


def test_a_blank_cell_is_one_space_between_the_pipes():
    assert Table(("A", "B"), (":---", ":---"), (("x", ""),)).markdown().splitlines()[2] == "| x | |"


def test_a_note_is_its_text():
    assert Note("Nothing yet.").markdown() == "Nothing yet."


def test_groups_write_a_heading_then_a_table_each():
    table = Table(("A",), (":---",), (("x",),))
    assert Groups((("One", table), ("Two", table))).markdown() == f"### One\n\n{table.markdown()}\n\n### Two\n\n{table.markdown()}"
