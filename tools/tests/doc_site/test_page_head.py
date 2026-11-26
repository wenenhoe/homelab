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
