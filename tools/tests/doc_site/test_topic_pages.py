"""The topic docs as pages, the diagrams in them, and the navigation that reaches them."""

from __future__ import annotations

import re
import shutil

import pytest
from doc_site import diagrams, site, vendor
from doc_site.diagrams import DiagramError, Drawn


def fake(sources: list[str]) -> list[Drawn]:
    return [Drawn(f'<svg id="l{i}"></svg>', f'<svg id="d{i}"></svg>') for i, _ in enumerate(sources)]


def build(tree, draw=fake):
    return site.build(tree, draw=draw)


def test_a_topic_doc_has_a_page_at_its_path_and_a_readme_is_its_directorys_page(tree):
    files = build(tree)
    assert "topics/index.html" in files
    assert "topics/infra/network/index.html" in files
    assert "topics/README/index.html" not in files


def test_the_generated_coverage_view_is_not_also_a_document(tree):
    paths = {path for path in build(tree) if path.startswith("topics/")}
    assert not any("coverage" in path for path in paths)


def test_a_link_between_topic_docs_reaches_the_page_from_its_depth(tree):
    files = build(tree)
    assert 'href="../../../topics/"' in files["topics/infra/network/index.html"].decode()
    assert 'href="../topics/infra/network/"' in files["topics/index.html"].decode().replace("../../", "../")


def test_a_page_reaches_its_assets_from_its_depth(tree):
    html = build(tree)["topics/infra/network/index.html"].decode()
    assert re.search(r'href="\.\./\.\./\.\./assets/site\.[0-9a-f]{10}\.css"', html)
    assert 'class="brand" href="../../../"' in html


def test_the_navigation_lists_topics_and_projects_and_marks_the_one_a_page_is_under(tree):
    html = build(tree)["topics/infra/network/index.html"].decode()
    assert re.search(r'<a href="\.\./\.\./\.\./topics/" aria-current="page">Topics</a>', html)
    assert re.search(r'<a href="\.\./\.\./\.\./projects/">Projects</a>', html)
    assert 'aria-current="page">Planning<' not in html


def test_a_project_is_under_projects_and_not_under_planning(tree):
    html = build(tree)["projects/one/index.html"].decode()
    assert re.search(r'aria-current="page">Projects</a>', html)
    assert 'aria-current="page">Planning<' not in html


def test_the_home_page_has_a_tile_for_each_entry(tree):
    html = build(tree)["index.html"].decode()
    for label in ("Planning", "Projects", "Decisions", "Topics", "DR coverage"):
        assert f"<strong>{label}</strong>" in html


def write_diagram(tree, name="network"):
    path = tree / f"docs/topics/infra/{name}.md"
    path.write_text("# The network\n\n```mermaid\ngraph TD\n  A --> B\n```\n\ntext\n\n```mermaid\ngraph LR\n  C --> D\n```\n", encoding="utf-8")
    return path


def test_a_diagram_is_drawn_in_both_renderings_and_the_source_is_not_shown(tree):
    write_diagram(tree)
    html = build(tree)["topics/infra/network/index.html"].decode()
    assert html.count('<figure class="diagram">') == 2
    assert '<div class="light"><svg id="l0"></svg></div><div class="dark"><svg id="d0"></svg></div>' in html
    assert '<svg id="l1">' in html
    assert "graph TD" not in html
    assert "<!--diagram" not in html


def test_every_diagram_of_the_site_is_drawn_in_one_call(tree):
    write_diagram(tree)
    other = tree / "docs/topics/infra/dns.md"
    other.write_text("# DNS\n\n```mermaid\ngraph TD\n  E --> F\n```\n", encoding="utf-8")
    calls = []

    def draw(sources):
        calls.append(list(sources))
        return fake(sources)

    build(tree, draw)
    assert len(calls) == 1
    assert len(calls[0]) == 3


def test_a_site_with_no_diagram_draws_none_and_starts_no_browser(tree):
    calls = []
    build(tree, lambda sources: calls.append(sources) or fake(sources))
    assert calls == [[]]


def test_a_diagram_that_does_not_draw_stops_the_build_at_its_file_and_line(tree):
    write_diagram(tree)

    def draw(sources):
        raise DiagramError("diagram 1: Parse error on line 2")

    with pytest.raises(DiagramError, match=r"docs/topics/infra/network\.md:10: Parse error on line 2"):
        build(tree, draw)


def test_the_anchors_are_read_without_drawing_anything(tree):
    write_diagram(tree)
    assert "the-network" in site.page_anchors(tree)["topics/infra/network"]


needs_chrome = pytest.mark.skipif(shutil.which("google-chrome") is None, reason="the diagrams are drawn in the installed Google Chrome")


@needs_chrome
def test_the_bundle_draws_a_diagram_in_both_themes_and_the_same_every_time():
    first = diagrams.draw(["graph TD\n  A[Start] --> B{Ok?}\n"])
    assert diagrams.draw(["graph TD\n  A[Start] --> B{Ok?}\n"]) == first
    (drawn,) = first
    assert drawn.light.startswith("<svg") and drawn.dark.startswith("<svg")
    assert drawn.light != drawn.dark
    assert "Start" in drawn.light
    assert 'id="mmd-0-light"' in drawn.light
    assert 'id="mmd-0-dark"' in drawn.dark


@needs_chrome
def test_a_diagram_mermaid_cannot_parse_is_an_error_naming_it():
    with pytest.raises(DiagramError, match="diagram 1"):
        diagrams.draw(["graph TD\n  A --> B\n", "this is not a diagram\n"])


@needs_chrome
def test_a_script_in_a_label_is_not_run_or_kept():
    (drawn,) = diagrams.draw(['graph TD\n  A["<img src=x onerror=alert(1)>"] --> B\n'])
    assert "onerror" not in drawn.light


def test_the_bundle_that_draws_is_the_one_the_pin_names():
    assert vendor.VENDOR / vendor.read_pin(vendor.MERMAID_PIN).name == diagrams.BUNDLE
