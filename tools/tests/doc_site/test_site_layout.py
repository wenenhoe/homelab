"""The layout check finds what it is meant to find, and passes the site the renderer builds."""

from __future__ import annotations

import shutil

import pytest
from doc_site import layout, site

pytest.importorskip("playwright")
pytestmark = pytest.mark.skipif(shutil.which("google-chrome") is None, reason="the layout check drives the installed Google Chrome")

PAGE = '<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><body style="margin:0;font:16px sans-serif">{body}</body>'


def problems(tmp_path, body: str, widths=(360,)) -> list[str]:
    (tmp_path / "index.html").write_text(PAGE.format(body=body), encoding="utf-8")
    return layout.check(tmp_path, widths)


def test_a_page_that_fits_has_no_problems(tmp_path):
    assert problems(tmp_path, "<p>Short text.</p>") == []


def test_a_page_that_scrolls_sideways_is_reported(tmp_path):
    assert any("scrolls sideways" in error for error in problems(tmp_path, '<div style="width:900px">wide</div>'))


def test_an_element_past_the_screen_edge_is_reported(tmp_path):
    assert any("past the" in error for error in problems(tmp_path, '<div style="position:absolute;left:300px;width:200px">edge</div>'))


def test_text_wider_than_its_box_is_reported(tmp_path):
    body = '<table><tr><td style="display:block;width:100px;overflow:hidden;white-space:nowrap">a very long unbreakable cell of text</td></tr></table>'
    assert any("px of content in a" in error for error in problems(tmp_path, body))


def test_text_under_twelve_pixels_is_reported(tmp_path):
    assert any("11px text" in error for error in problems(tmp_path, '<p style="font-size:11px">small</p>'))


def test_text_of_twelve_pixels_passes(tmp_path):
    assert problems(tmp_path, '<p style="font-size:12px">fine</p>') == []


def test_text_hidden_for_screen_readers_is_not_measured(tmp_path):
    hidden = "position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)"
    body = f'<div style="{hidden}"><p style="font-size:9px;width:300px;white-space:nowrap">hidden header</p></div>'
    assert problems(tmp_path, body) == []


def test_every_page_and_width_is_named_in_the_error(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a/index.html").write_text(PAGE.format(body='<p style="font-size:9px">x</p>'), encoding="utf-8")
    (error,) = layout.check(tmp_path, (390,))
    assert error.startswith("/a/ at 390px: ")


def test_a_menu_button_that_does_not_open_the_menu_is_reported(tmp_path):
    body = '<button class="menu-btn">Menu</button><dialog class="drawer"></dialog>'
    assert any("does not open the menu" in error for error in problems(tmp_path, body))


def test_a_directory_without_pages_is_reported(tmp_path):
    assert layout.check(tmp_path) == [f"{tmp_path} has no pages"]


def test_the_site_the_renderer_builds_fits_every_width(tree, tmp_path):
    out = tmp_path / "site"
    site.write(out, tree)
    assert layout.check(out) == []


def test_the_pages_of_a_site_are_its_urls(tmp_path):
    for path in ("index.html", "a/index.html", "b/c/index.html"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("x", encoding="utf-8")
    assert layout.pages_of(tmp_path) == ["/", "/a/", "/b/c/"]
