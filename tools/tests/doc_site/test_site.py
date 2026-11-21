"""The built site: the same bytes every time, the anchors GitHub gives, and the markdown of the views unchanged."""

from __future__ import annotations

import base64
import hashlib
import re

import pytest
from doc_scripts.generate_doc_indexes import intro_path
from doc_site import site
from doc_site.markup import UnsupportedMarkup, github_slug

PAGES = {"index.html", *(f"{view.slug}/index.html" for view in site.VIEWS)}
STAMP = site.Stamp("0123456789abcdef0123456789abcdef01234567", "2026-11-21T16:12:00+08:00")


def asset(files: dict[str, bytes], stem: str, extension: str) -> str:
    """The path of the one fingerprinted `assets/<stem>.<hash>.<extension>` in `files`."""
    (path,) = [path for path in files if re.fullmatch(rf"assets/{stem}\.[0-9a-f]{{10}}\.{extension}", path)]
    return path


def test_the_site_is_these_files(tree):
    files = site.build(tree)
    assert set(files) == PAGES | {"assets/simple-licence.txt", asset(files, "site", "css"), asset(files, "site", "js"), asset(files, "simple", "css")}


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
    files = site.build(tree)
    assert files[asset(files, "simple", "css")] == (site.PACKAGE / "vendor/simple.min.css").read_bytes()


def test_the_licence_served_is_the_vendored_one(tree):
    assert site.build(tree)["assets/simple-licence.txt"] == (site.PACKAGE / "vendor/simple.LICENSE").read_bytes()


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
    path = tree / intro_path(site.VIEWS[0].source)
    path.write_text(path.read_text().replace("A second paragraph.", "- a list"), encoding="utf-8")
    with pytest.raises(UnsupportedMarkup):
        site.build(tree)


def test_a_hand_written_section_in_an_introduction_stops_the_build(tree):
    # The sections of a view are its rows; a section written by hand would be dropped from the page without a word.
    path = tree / intro_path(site.VIEWS[0].source)
    path.write_text(path.read_text() + "\n## Notes\n\ntext\n", encoding="utf-8")
    with pytest.raises(UnsupportedMarkup, match="sections of a view are generated"):
        site.build(tree)


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
        stylesheet = asset(files, "simple", "css")
        expected = "sha384-" + base64.b64encode(hashlib.sha384(files[stylesheet]).digest()).decode()
        for path, data in files.items():
            if path.endswith("index.html"):
                assert f'{stylesheet}" integrity="{expected}"' in data.decode(), path

    def test_the_value_is_the_one_openssl_gives(self):
        # sha384 of the empty string, in the form the attribute takes.
        assert site.integrity(b"") == "sha384-OLBgp1GsljhM2TJ+sbHjaiH9txEUvgdDTAzHv2P24donTt6/529l+9Ua0vFImLlb"


class TestFingerprints:
    def test_a_name_carries_ten_hex_of_the_files_sha256(self):
        assert site.fingerprinted("site.css", b"") == "assets/site.e3b0c44298.css"

    def test_every_page_names_the_files_it_loads(self, tree):
        files = site.build(tree)
        names = [asset(files, "site", "css"), asset(files, "site", "js"), asset(files, "simple", "css")]
        for path in PAGES:
            html = files[path].decode()
            assert all(name in html for name in names), path

    def test_a_name_changes_when_the_content_does(self):
        assert site.fingerprinted("a.css", b"x") != site.fingerprinted("a.css", b"y")


class TestFooter:
    def test_a_stamped_build_names_its_commit_and_date(self, tree):
        for path in PAGES:
            html = site.build(tree, STAMP)[path].decode()
            assert f'<a href="{site.REPO_URL}/commit/{STAMP.sha}"><code>0123456</code></a>' in html, path
            assert '<time datetime="2026-11-21T16:12:00+08:00">2026-11-21 08:12 UTC</time>' in html, path
            assert "Local build" not in html

    def test_an_unstamped_build_says_it_is_local(self, tree):
        html = site.build(tree)["index.html"].decode()
        assert "Local build" in html and "/commit/" not in html

    def test_the_footer_credits_simple_css_and_links_its_licence(self, tree):
        files = site.build(tree)
        assert 'href="assets/simple-licence.txt"' in files["index.html"].decode()
        assert 'href="../assets/simple-licence.txt"' in files["decision-index/index.html"].decode()
        assert "Simple.css" in files["index.html"].decode()

    def test_a_stamped_build_is_the_same_bytes_every_time(self, tree):
        assert site.build(tree, STAMP) == site.build(tree, STAMP)

    @pytest.mark.parametrize("sha", ["", "abc1234", "G" * 40, "0" * 39, "0" * 41, "main"])
    def test_a_commit_that_is_not_a_full_id_is_refused(self, sha):
        with pytest.raises(ValueError, match="full commit id"):
            site.Stamp(sha, "2026-11-21T16:12:00+08:00")

    def test_a_date_that_is_not_iso_is_refused(self):
        with pytest.raises(ValueError):
            site.Stamp("0" * 40, "yesterday")
