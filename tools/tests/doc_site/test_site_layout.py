"""The layout check finds what it is meant to find, and passes the site the renderer builds."""

from __future__ import annotations

import contextlib
import io
import shutil

import pytest
from doc_site import layout, site

pytest.importorskip("playwright")
pytestmark = pytest.mark.skipif(shutil.which("google-chrome") is None, reason="the layout check drives the installed Google Chrome")

PAGE = '<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><body style="margin:0;font:16px sans-serif">{body}</body>'


def problems(tmp_path, body: str, viewports=(360,)) -> list[str]:
    (tmp_path / "index.html").write_text(PAGE.format(body=body), encoding="utf-8")
    return layout.check(tmp_path, viewports)


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


BAR = '<div style="position:sticky;top:0;height:{height}px;background:#ccc">bar</div>'


def test_a_bar_that_takes_a_fifth_of_a_short_screen_is_reported(tmp_path):
    errors = problems(tmp_path, BAR.format(height=100) + "<p>text</p>" * 80, [(844, 390)])
    assert errors and "stays on screen and takes 26% of the 390px height" in errors[0] and errors[0].startswith("/ at 844x390px: ")


def test_the_same_bar_on_a_tall_screen_passes(tmp_path):
    assert problems(tmp_path, BAR.format(height=100) + "<p>text</p>" * 80, [(844, 800)]) == []


def test_a_bar_that_scrolls_away_is_not_held_to_the_share(tmp_path):
    assert problems(tmp_path, BAR.format(height=100).replace("sticky", "static"), [(844, 390)]) == []


def test_a_heading_a_link_leaves_under_the_bar_is_reported(tmp_path):
    body = BAR.format(height=60) + '<a href="#h">go</a>' + "<p>text</p>" * 80 + '<h2 id="h">Heading</h2>' + "<p>text</p>" * 80
    assert any("#h lands" in error and "under the bar" in error for error in problems(tmp_path, body))


def test_a_heading_clear_of_the_bar_passes(tmp_path):
    body = (
        "<style>html{scroll-padding-top:70px}</style>"
        + BAR.format(height=60)
        + '<a href="#h">go</a>'
        + "<p>text</p>" * 80
        + '<h2 id="h">Heading</h2>'
        + "<p>text</p>" * 80
    )
    assert problems(tmp_path, body) == []


def test_a_link_to_nothing_is_reported(tmp_path):
    assert any("#gone names nothing" in error for error in problems(tmp_path, '<a href="#gone">x</a>'))


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


def test_a_width_that_changes_the_page_is_judged_after_the_page_is_resized(tmp_path):
    body = "<style>@media (max-width:400px){p{font-size:9px}}</style><p>x</p>"
    assert [error.split(": ")[0] for error in problems(tmp_path, body, (360, 768))] == ["/ at 360px"]


def test_pages_shared_among_browsers_are_reported_in_the_order_of_the_pages_and_widths(tmp_path):
    for name in "abcde":
        (tmp_path / name).mkdir()
        (tmp_path / name / "index.html").write_text(PAGE.format(body='<p style="font-size:9px">x</p>'), encoding="utf-8")
    errors = layout.check(tmp_path, (390, 360), workers=3)
    assert [error.split(": ")[0] for error in errors] == [f"/{name}/ at {width}px" for name in "abcde" for width in (390, 360)]


ORIENTED_PAGE = '<nav class="toc"></nav><div style="width:{width}px">wide</div>'


def sizes_reported(tmp_path, body: str) -> set[str]:
    return {error.split(": ")[0] for error in problems(tmp_path, body, (1400,))}


def test_a_page_with_a_list_is_also_opened_at_the_wide_sizes(tmp_path):
    assert sizes_reported(tmp_path, ORIENTED_PAGE.format(width=1000)) == set()
    assert sizes_reported(tmp_path, ORIENTED_PAGE.format(width=1500)) == {"/ at 1400px", "/ at 1040px", "/ at 1280px"}


def test_a_fault_at_the_narrowest_width_with_a_list_column_alone_is_reported(tmp_path):
    body = "<style>@media (min-width:1040px) and (max-width:1100px){p{font-size:9px}}</style><nav class='toc'></nav><p>x</p>"
    assert sizes_reported(tmp_path, body) == {"/ at 1040px"}


def test_a_page_without_a_list_or_tabs_is_not_opened_at_the_wide_size(tmp_path):
    assert sizes_reported(tmp_path, '<div style="width:1500px">wide</div>') == {"/ at 1400px"}


def test_a_page_with_tabs_is_opened_at_the_wide_size(tmp_path):
    assert "/ at 1280px" in sizes_reported(tmp_path, '<div class="tabs"></div><div style="width:1500px">wide</div>')


def write_pages(directory, paths: list[str]) -> None:
    for path in paths:
        page = directory / path.strip("/") / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(PAGE.format(body="<p>x</p>"), encoding="utf-8")


def a_site(directory, per_section: int) -> list[str]:
    sections = ("projects", "decisions", "topics", "architecture")
    paths = ["/", "/project-planning/", "/decision-index/", "/dr-coverage/", *(f"/{s}/" for s in sections)]
    paths += [f"/{s}/doc-{n:03}/" for s in sections for n in range(per_section)]
    write_pages(directory, paths)
    return paths


def test_the_sample_has_the_home_page_the_views_the_landings_and_a_page_of_each_section(tmp_path):
    paths = a_site(tmp_path, 3)
    assert layout.sample_of(tmp_path) == [
        "/",
        "/architecture/",
        "/architecture/doc-000/",
        "/decision-index/",
        "/decisions/",
        "/decisions/doc-000/",
        "/dr-coverage/",
        "/project-planning/",
        "/projects/",
        "/projects/doc-000/",
        "/topics/",
        "/topics/doc-000/",
    ]
    assert set(layout.sample_of(tmp_path)) < set(paths)


def test_the_sample_adds_the_longest_page_that_lists_its_headings(tmp_path):
    a_site(tmp_path, 3)
    for path, size in (("/topics/doc-001/", 5), ("/decisions/doc-002/", 90), ("/projects/doc-001/", 20)):
        (tmp_path / path.strip("/") / "index.html").write_text(PAGE.format(body='<nav class="toc"></nav>' + "<p>text</p>" * size), encoding="utf-8")
    sample = layout.sample_of(tmp_path)
    assert "/decisions/doc-002/" in sample and "/topics/doc-001/" not in sample and "/projects/doc-001/" not in sample


def test_the_sample_does_not_grow_with_the_number_of_pages(tmp_path):
    a_site(tmp_path, 120)
    (tmp_path / "topics/doc-077/index.html").write_text(PAGE.format(body='<nav class="toc"></nav>' + "<p>text</p>" * 200), encoding="utf-8")
    sample = layout.sample_of(tmp_path)
    assert len(layout.pages_of(tmp_path)) > 480 and "/topics/doc-077/" in sample
    assert len(sample) <= layout.MAX_SAMPLE


def test_a_site_with_no_long_page_still_has_a_sample(tmp_path):
    a_site(tmp_path, 1)
    assert layout.sample_of(tmp_path)


def test_check_opens_only_the_pages_it_is_given(tmp_path):
    for name in "abc":
        (tmp_path / name).mkdir()
        (tmp_path / name / "index.html").write_text(PAGE.format(body='<p style="font-size:9px">x</p>'), encoding="utf-8")
    assert [e.split(": ")[0] for e in layout.check(tmp_path, (390,), pages=["/b/"])] == ["/b/ at 390px"]


@pytest.mark.parametrize(
    ("path", "page"),
    [
        ("docs/topics/deploy/ansible.md", "/topics/deploy/ansible/"),
        ("docs/topics/README.md", "/topics/"),
        ("docs/README.md", "/guide/"),
        ("docs/decisions/0001-a/revision-001.md", "/decisions/0001-a/revision-001/"),
        ("docs/projects/doc-site-pages.md", "/projects/doc-site-pages/"),
        ("tools/doc_site/layout.py", None),
        ("docs/diagram.png", None),
        ("README.md", "/"),
        ("tools/doc_scripts/view_intros/home.md", "/"),
        ("tools/doc_scripts/view_intros/coverage.md", None),
    ],
)
def test_a_changed_document_is_the_page_the_site_builds_for_it(path, page):
    assert layout.page_of_document(path) == page
    if page not in (None, "/"):
        assert page.strip("/") == site._slug(path)


def test_the_sample_adds_the_page_of_each_changed_document_that_has_one(tmp_path):
    a_site(tmp_path, 5)
    sample = layout.sample_of(tmp_path, ["docs/topics/doc-004.md", "docs/decisions/doc-003.md", "docs/topics/gone.md", "tools/x.py"])
    assert {"/topics/doc-004/", "/decisions/doc-003/"} <= set(sample)
    assert "/topics/gone/" not in sample and len(sample) == len(layout.sample_of(tmp_path)) + 2


def test_a_changed_page_already_in_the_sample_is_not_added_twice(tmp_path):
    a_site(tmp_path, 5)
    assert layout.sample_of(tmp_path, ["docs/topics/doc-000.md", "docs/topics/README.md", "README.md"]) == layout.sample_of(tmp_path)


def run_main(tmp_path, changed: list[str], *flags: str) -> str:
    listing = tmp_path / "changed.txt"
    listing.write_text("\n".join(changed) + "\n", encoding="utf-8")
    site_dir = tmp_path / "site"
    a_site(site_dir, 5)
    (site_dir / "topics/doc-004/index.html").write_text(PAGE.format(body='<p style="font-size:9px">x</p>'), encoding="utf-8")
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        layout.main([*flags, "--changed", str(listing), str(site_dir)])
    return buffer.getvalue()


def test_a_fault_on_a_changed_document_fails_the_sample(tmp_path):
    assert "/topics/doc-004/ at 360px" in run_main(tmp_path, ["docs/topics/doc-004.md"], "--sample")


def test_a_fault_on_a_page_nothing_changed_passes_the_sample(tmp_path):
    assert run_main(tmp_path, ["docs/topics/doc-001.md"], "--sample") == ""


def test_a_change_to_the_renderer_checks_every_page(tmp_path):
    assert "/topics/doc-004/ at 360px" in run_main(tmp_path, ["tools/doc_site/site.py"], "--sample")


def test_changed_without_sample_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        run_main(tmp_path, [])


def test_a_heading_shown_only_by_its_address_is_reached_by_it(tmp_path):
    body = (
        "<style>html{scroll-padding-top:70px}.p{display:none}.p:has(:target){display:block}</style>"
        + BAR.format(height=60)
        + '<a href="#h">go</a>'
        + "<p>text</p>" * 80
        + '<div class="p"><h2 id="h">Heading</h2></div>'
        + "<p>text</p>" * 80
    )
    assert problems(tmp_path, body) == []
