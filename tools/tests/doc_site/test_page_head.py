"""What a page says about itself: its name in the tab and the header, what a link preview reads and its icon."""

from __future__ import annotations

import html
import re

from doc_site import site


def title(page: bytes) -> str:
    return html.unescape(re.search(r"<title>(.*?)</title>", page.decode())[1])


def test_the_home_page_is_titled_for_its_owner_and_every_other_page_for_the_site(tree):
    files = site.build(tree)
    assert title(files["index.html"]) == "wenenhoe's Homelab"
    assert title(files["projects/one/index.html"]).endswith(" · Homelab")
    assert title(files["decision-index/index.html"]) == "Decisions view · Homelab"


def test_the_header_names_the_site(tree):
    for path, data in site.build(tree).items():
        if path.endswith(".html"):
            assert re.search(r'<a class="brand" href="[^"]*">Homelab</a>', data.decode()), path


def meta(page: bytes, key: str) -> str:
    return html.unescape(re.search(rf'<meta (?:name|property)="{key}" content="([^"]*)">', page.decode())[1])


def test_every_page_gives_a_link_preview_its_title_and_description_and_no_image(tree):
    for path, data in site.build(tree).items():
        if path.endswith(".html"):
            assert meta(data, "og:title") == title(data), path
            assert meta(data, "og:description") == meta(data, "description") != "", path
            assert meta(data, "og:site_name") == "wenenhoe's Homelab", path
            assert "og:image" not in data.decode(), path


def test_a_project_is_described_by_its_summary(tree):
    path = tree / "docs/projects/one.md"
    text, count = re.subn(r"(?m)^summary:.*$", """summary: 'Move "a" & <b> across.'""", path.read_text(encoding="utf-8"))
    assert count == 1
    path.write_text(text, encoding="utf-8")
    page = site.build(tree)["projects/one/index.html"]
    assert meta(page, "description") == 'Move "a" & <b> across.'


def test_a_view_is_described_by_its_lede_as_plain_text(tree):
    assert meta(site.build(tree)["decision-index/index.html"], "description") == "A view with a link, code and bold text."


def test_a_page_with_no_summary_of_its_own_has_the_sites_description(tree):
    files = site.build(tree)
    for path in ("index.html", "topics/infra/network/index.html"):
        assert meta(files[path], "description") == site.DESCRIPTION, path
