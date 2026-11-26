"""The home page shows parts of the root README, and the architecture docs are pages under their own entry."""

from __future__ import annotations

import re

import pytest
from doc_site import home, site
from doc_site.markup import UnsupportedMarkup


def build(tree) -> dict[str, str]:
    return {path: data.decode() for path, data in site.build(tree).items() if path.endswith(".html")}


def test_the_home_page_shows_the_slots_of_the_root_readme_under_the_templates_title(tree):
    page = build(tree)["index.html"]
    assert '<h1 id="home">Home</h1>' in page
    assert "What the lab is." in page and "One box." in page
    assert '<h2 id="architecture">Architecture</h2>' in page and '<h2 id="hardware">Hardware</h2>' in page
    assert "Not on the site." not in page and "badge" not in page and "A lab" not in page


def test_a_heading_in_a_code_block_ends_no_slot(tree):
    readme = tree / home.README
    readme.write_text(readme.read_text().replace("One box.", "```text\n## not a section\n```\n\nOne box."), encoding="utf-8")
    assert "One box." in build(tree)["index.html"]


def test_a_slot_for_a_section_the_readme_lacks_stops_the_build(tree):
    readme = tree / home.README
    readme.write_text(readme.read_text().replace("## Hardware", "## Machines"), encoding="utf-8")
    with pytest.raises(UnsupportedMarkup, match="no `##` section with the anchor 'hardware'"):
        site.build(tree)


def test_a_relative_link_in_the_template_stops_the_build(tree):
    template = tree / home.TEMPLATE
    template.write_text(template.read_text() + "\n[near](home.md)\n", encoding="utf-8")
    with pytest.raises(UnsupportedMarkup, match="relative link"):
        site.build(tree)


def test_links_of_the_root_readme_go_to_pages_from_the_root(tree):
    page = build(tree)["index.html"]
    assert 'href="topics/"' in page and 'href="architecture/"' in page


def test_the_home_page_has_a_tile_for_each_entry_and_links_its_two_files(tree):
    page = build(tree)["index.html"]
    assert re.findall(r'<a class="tile" href="([^"]+)">', page) == [
        "project-planning/",
        "projects/",
        "decision-index/",
        "topics/",
        "architecture/",
        "dr-coverage/",
    ]
    for source in (home.README, home.TEMPLATE):
        assert f'<a href="https://github.com/wenenhoe/homelab/blob/main/{source}"><code>{source}</code></a>' in page


def test_the_menu_of_the_home_page_lists_the_sections_it_shows(tree):
    assert '<h2>On this page</h2><a href="#architecture">Architecture</a><a href="#hardware">Hardware</a>' in build(tree)["index.html"]


def test_the_readme_of_docs_is_the_guide_page(tree):
    files = build(tree)
    assert '<h1 id="docs-where-things-go">Docs: where things go</h1>' in files["guide/index.html"]
    assert 'href="../topics/"' in files["guide/index.html"]
    assert '<a href="../guide/">home</a>' in files["architecture/index.html"]


def test_the_architecture_docs_are_pages_and_the_navigation_marks_their_entry(tree):
    files = build(tree)
    assert '<a href="../architecture/" aria-current="page">Architecture</a>' in files["architecture/index.html"]
    flow = files["architecture/flow/index.html"]
    assert '<a href="../../architecture/" aria-current="page">Architecture</a>' in flow
    assert '<h2 id="steps">Steps</h2>' in flow
    assert 'href="../../architecture/"' in flow


def test_the_navigation_lists_architecture_between_topics_and_dr_coverage(tree):
    labels = re.findall(
        r"<a href=\"[^\"]+\"(?: aria-current=\"page\")?>([^<]+)</a>", re.search(r'<nav aria-label="Views">.*?</nav>', build(tree)["index.html"])[0]
    )
    assert labels == ["Planning", "Projects", "Decisions", "Topics", "Architecture", "DR coverage"]


def test_the_anchors_a_link_can_name_include_the_home_page_and_architecture(tree):
    anchors = site.page_anchors(tree)
    assert "hardware" in anchors[""] and "kinds" in anchors["guide"]
    assert "steps" in anchors["architecture/flow"]
