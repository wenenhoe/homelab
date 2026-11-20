"""The built site: the same bytes every time, the anchors GitHub gives, and the markdown of the views unchanged."""

from __future__ import annotations

import base64
import hashlib
import re

import pytest
from doc_scripts.generate_doc_indexes import generated_blocks
from doc_site import site
from doc_site.markup import UnsupportedMarkup, github_slug

EXPECTED_FILES = {"index.html", "assets/site.css", "assets/site.js", "assets/simple.css", *(f"{view.slug}/index.html" for view in site.VIEWS)}


def test_the_site_is_these_files(tree):
    assert set(site.build(tree)) == EXPECTED_FILES


def test_two_builds_of_one_tree_are_the_same_bytes(tree):
    assert site.build(tree) == site.build(tree)


def test_two_builds_into_directories_are_the_same_bytes(tree, tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    site.write(first, tree)
    site.write(second, tree)
    read = lambda out: {path.relative_to(out).as_posix(): path.read_bytes() for path in out.rglob("*") if path.is_file()}  # noqa: E731
    assert read(first) == read(second)


def test_writing_into_a_directory_with_files_is_refused(tree, tmp_path):
    (tmp_path / "stale").write_text("x")
    with pytest.raises(SystemExit):
        site.write(tmp_path, tree)


def test_the_stylesheet_is_the_vendored_file(tree):
    assert site.build(tree)["assets/simple.css"] == (site.PACKAGE / "vendor/simple.min.css").read_bytes()


def headings(html: str) -> list[tuple[str, str]]:
    """(anchor, text) of every heading on a page: the h1, each section's h2 (the id is on the section) and each h3."""
    found = re.findall(r'<(?:h1|h3) id="([^"]+)">(.*?)</h[13]>|<section id="([^"]+)"><h2>(.*?)</h2>', html)
    return [(a or c, re.sub(r"<[^>]+>", "", b or d).replace("&amp;", "&")) for a, b, c, d in found]


def test_every_heading_has_the_anchor_github_gives_it(tree):
    built = site.build(tree)
    for view in site.VIEWS:
        html = built[f"{view.slug}/index.html"].decode()
        found = headings(html)
        assert len(found) >= 2, view.slug
        seen: dict[str, int] = {}
        for anchor, text in found:
            slug = github_slug(text)
            n = seen.get(slug, 0)
            seen[slug] = n + 1
            assert anchor == (slug if n == 0 else f"{slug}-{n}"), (view.slug, text)


def test_the_anchors_a_link_can_name_are_those_of_the_headings(tree):
    anchors = site.page_anchors(tree)
    assert set(anchors) == {"", *(view.slug for view in site.VIEWS)}
    built = site.build(tree)
    for view in site.VIEWS:
        html = built[f"{view.slug}/index.html"].decode()
        assert {anchor for anchor, _ in headings(html)} <= anchors[view.slug]


def test_a_link_into_a_view_reaches_the_same_section_on_its_page(tree):
    html = site.build(tree)["project-planning/index.html"].decode()
    assert 'href="../decision-index/#by-number"' in html
    assert 'id="by-number"' in site.build(tree)["decision-index/index.html"].decode()


def test_the_pages_hold_the_rows_of_the_generator(tree):
    html = site.build(tree)["project-planning/index.html"].decode()
    assert "one.md" in html and "two.md" in html


def test_markup_the_renderer_does_not_know_stops_the_build(tree):
    path = tree / site.VIEWS[0].source
    path.write_text(path.read_text().replace("A second paragraph.", "- a list"), encoding="utf-8")
    with pytest.raises(UnsupportedMarkup):
        site.build(tree)


def test_a_hand_written_section_is_not_published_silently(tree):
    # The views hold generated sections only below their introduction; the title and intro are read, the rest is the rows.
    headings = {g.heading for g in generated_blocks(tree)}
    assert "Placeholder" not in headings


class TestRoles:
    def test_status_and_title_columns(self):
        roles = site.roles_of(("Project", "Initiative", "Status", "Summary"))
        assert roles[0] == "title" and roles[2] == "status"

    def test_a_decision_number_is_an_eyebrow(self):
        assert site.roles_of(("ADR", "Decision", "Status"))[0] == "eyebrow"

    @pytest.mark.parametrize("cell", ["Building", "Not started", "blocked: x"])
    def test_a_status_has_a_key(self, cell):
        assert re.fullmatch(r"[a-z-]*", site.status_key(cell))


class TestIntegrity:
    def test_the_stylesheet_link_carries_the_sha384_of_the_vendored_file(self, tree):
        files = site.build(tree)
        expected = "sha384-" + base64.b64encode(hashlib.sha384(files["assets/simple.css"]).digest()).decode()
        for path, data in files.items():
            if path.endswith("index.html"):
                assert f'assets/simple.css" integrity="{expected}"' in data.decode(), path

    def test_the_value_is_the_one_openssl_gives(self):
        # sha384 of the empty string, in the form the attribute takes.
        assert site.integrity(b"") == "sha384-OLBgp1GsljhM2TJ+sbHjaiH9txEUvgdDTAzHv2P24donTt6/529l+9Ua0vFImLlb"
