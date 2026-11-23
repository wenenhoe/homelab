"""The home page carries the README of `docs/`, and the architecture docs are pages under their own entry."""

from __future__ import annotations

import re

from doc_site import site


def build(tree) -> dict[str, str]:
    return {path: data.decode() for path, data in site.build(tree).items() if path.endswith(".html")}


def test_the_readme_of_docs_is_the_body_of_the_home_page_and_no_page_of_its_own(tree):
    files = build(tree)
    home = files["index.html"]
    assert "<h1>Homelab docs</h1>" in home
    assert '<h2 id="docs-where-things-go">Docs: where things go</h2>' in home
    assert '<h2 id="kinds">Kinds</h2>' in home
    assert [path for path in files if "readme" in path.lower()] == []


def test_the_home_page_keeps_its_tiles_and_links_to_the_readme_on_github(tree):
    home = build(tree)["index.html"]
    assert re.findall(r'<a class="tile" href="([^"]+)">', home) == [
        "project-planning/",
        "projects/",
        "decision-index/",
        "topics/",
        "architecture/",
        "dr-coverage/",
    ]
    assert '<a href="https://github.com/wenenhoe/homelab/blob/main/docs/README.md">View this file on GitHub</a>' in home


def test_links_in_the_readme_go_to_pages_from_the_root(tree):
    home = build(tree)["index.html"]
    assert 'href="topics/"' in home
    assert 'href="architecture/"' in home


def test_the_menu_of_the_home_page_lists_the_headings_of_the_readme(tree):
    assert '<h2>On this page</h2><a href="#kinds">Kinds</a>' in build(tree)["index.html"]


def test_a_link_to_the_readme_of_docs_from_a_page_goes_to_the_home_page(tree):
    assert '<a href="../">home</a>' in build(tree)["architecture/index.html"]


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
    assert "kinds" in anchors[""]
    assert "steps" in anchors["architecture/flow"]
