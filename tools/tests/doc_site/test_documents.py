"""A document as HTML: what it keeps, what it refuses, and the anchors and links it carries."""

from __future__ import annotations

import pytest
from doc_site.documents import render
from doc_site.markup import UnsupportedMarkup


def same(target: str) -> str:
    return target


def html_of(body: str, resolve=same) -> str:
    return render(f"---\nid: x\n---\n\n# Title\n\n{body}", resolve, "doc.md").html


def test_the_first_heading_is_the_title_and_the_front_matter_is_left_off():
    page = render("---\nid: x\n---\n\n# A title\n\ntext\n", same)
    assert page.title == "A title"
    assert page.title_id == "a-title"
    assert "A title" not in page.html
    assert "id: x" not in page.html


def test_a_document_without_a_title_is_refused():
    with pytest.raises(UnsupportedMarkup, match="no `# ` title"):
        render("text\n", same, "doc.md")


def test_headings_take_the_anchor_github_gives_and_repeats_are_numbered():
    page = render("# T\n\n## Scope\n\n### Same\n\n### Same\n\n## `Code` & more\n", same)
    assert [(h.level, h.id) for h in page.headings] == [(2, "scope"), (3, "same"), (3, "same-1"), (2, "code--more")]
    assert '<h2 id="scope">Scope</h2>' in page.html
    assert '<h3 id="same-1">' in page.html


def test_a_link_is_turned_into_the_address_the_page_uses():
    assert 'href="/x/other/"' in html_of("[a](other.md)", lambda target: "/x/" + target.removesuffix(".md") + "/")


def test_an_html_comment_is_dropped_and_other_html_is_refused():
    assert "hidden" not in html_of("<!-- hidden -->\n\ntext\n")
    assert "hidden" not in html_of("a <!-- hidden --> b\n")
    with pytest.raises(UnsupportedMarkup, match=r"doc.md:\d+: HTML .* is not rendered"):
        html_of("<div>x</div>\n")
    with pytest.raises(UnsupportedMarkup, match="markup of type 'html_inline'"):
        html_of("a <b>x</b> b\n")


def test_an_image_is_refused():
    with pytest.raises(UnsupportedMarkup, match="an image is not rendered"):
        html_of("![alt](a.png)\n")


def test_a_mermaid_block_is_refused_until_the_site_draws_it():
    with pytest.raises(UnsupportedMarkup, match="a Mermaid diagram is not rendered"):
        html_of("```mermaid\ngraph TD\n```\n")


def test_other_code_blocks_are_kept():
    assert "<pre><code" in html_of("```sh\nls\n```\n")


def test_a_task_list_item_is_a_disabled_box():
    out = html_of("- [ ] open\n- [x] done\n- plain\n")
    assert out.count('<input type="checkbox" disabled') == 2
    assert out.count("checked>") == 1
    assert '<ul class="tasks">' in out
    assert '<li class="task">' in out
    assert "[ ]" not in out


def test_a_list_with_no_task_keeps_its_bullets():
    out = html_of("- one\n- two\n")
    assert "<ul>" in out
    assert "tasks" not in out


def test_a_table_cell_carries_its_header_and_a_status_is_a_pill():
    out = html_of("| Stage | Status |\n| --- | :-: |\n| One | Done |\n| Two |  |\n")
    assert '<td data-label="Stage" class="field">One</td>' in out
    assert '<span class="pill s-done">Done</span>' in out
    assert 'data-label="Status" class="field none"' in out
    assert "style=" not in out


def test_the_error_names_the_line():
    with pytest.raises(UnsupportedMarkup, match=r"doc.md:7:"):
        render("---\nid: x\n---\n\n# T\n\n<div>\n", same, "doc.md")
