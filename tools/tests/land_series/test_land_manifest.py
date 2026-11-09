"""Reading a series file and putting its layers in landing order."""

from __future__ import annotations

import pytest
from _series_repo import Author, series_file
from land_series.manifest import Layer, SeriesError, order_layers, parse_series
from land_series.replay import stopped_by


def layer(layer_id: str, slug: str | None = None, source: str = "series") -> Layer:
    return Layer(id=layer_id, slug=slug or f"slug-{layer_id}", patch=b"", subject="s", authored=0, diff_headers=(), source=source)


def test_each_layer_carries_its_slug_subject_date_and_touched_files(author: Author) -> None:
    first = author.patch("docs: add a note", {"docs/note.md": "one\n"})
    second = author.patch("fix: tidy the note", {"docs/note.md": "two\n", "docs/other.md": "x\n"})
    layers = parse_series(series_file([("0001a first-note", first), ("0001b tidy-note", second)]))

    assert [(item.id, item.slug) for item in layers] == [("0001a", "first-note"), ("0001b", "tidy-note")]
    assert [item.subject for item in layers] == ["docs: add a note", "fix: tidy the note"]
    assert layers[1].authored - layers[0].authored == 60
    assert layers[1].diff_headers == ("a/docs/note.md b/docs/note.md", "a/docs/other.md b/docs/other.md")
    assert layers[0].patch.startswith(b"From ")


def test_a_long_subject_is_unfolded_and_loses_its_patch_tag(author: Author) -> None:
    long_subject = "docs: " + "record how past series fared in the patch series exploration " * 2
    patch = author.patch(long_subject.strip(), {"a.txt": "a\n"})
    layers = parse_series(series_file([("0001a long-one", patch)]))

    assert layers[0].subject == long_subject.strip()


def test_comments_and_blank_lines_in_the_manifest_are_skipped(author: Author) -> None:
    patch = author.patch("docs: a", {"a.txt": "a\n"})
    data = b"# a series\n\n0001a only-one\n\n" + patch

    assert [item.id for item in parse_series(data)] == ["0001a"]


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        pytest.param("0001a one\n0001b two\n", "lists 2 layers but the mbox holds 1", id="more layers than patches"),
        pytest.param("0001 one\n", "not a layer id", id="id without a letter"),
        pytest.param("0001A one\n", "not a layer id", id="uppercase letter"),
        pytest.param("S0001a one\n", "not a layer id", id="security series id"),
        pytest.param("0001a Bad_Slug\n", "not a branch slug", id="slug with capitals"),
        pytest.param("0001a\n", "an id and a branch slug", id="no slug"),
        pytest.param("0001a one two\n", "an id and a branch slug", id="a third word"),
    ],
)
def test_a_malformed_manifest_names_the_problem(author: Author, manifest: str, message: str) -> None:
    patch = author.patch("docs: a", {"a.txt": "a\n"})

    with pytest.raises(SeriesError, match=message):
        parse_series(manifest.encode() + b"\n" + patch)


def test_a_file_with_no_patches_is_refused() -> None:
    with pytest.raises(SeriesError, match="no patches"):
        parse_series(b"0001a one\n")


def test_layers_from_several_files_land_in_id_order() -> None:
    ordered = order_layers([layer("0002a"), layer("0001b"), layer("0001a")])

    assert [item.id for item in ordered] == ["0001a", "0001b", "0002a"]


@pytest.mark.parametrize(
    ("layers", "message"),
    [
        pytest.param([layer("0001a"), layer("0001a", slug="other", source="b")], "layer 0001a is listed twice", id="duplicate id"),
        pytest.param([layer("0001a", slug="same"), layer("0002a", slug="same")], "share the branch slug", id="duplicate slug"),
    ],
)
def test_layers_that_cannot_be_ordered_are_refused(layers: list[Layer], message: str) -> None:
    with pytest.raises(SeriesError, match=message):
        order_layers(layers)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        pytest.param(("a/docs/x.md b/docs/x.md",), [], id="a doc"),
        pytest.param(("a/.githooks/pre-applypatch b/.githooks/pre-applypatch",), [".githooks/pre-applypatch"], id="a hook"),
        pytest.param(("a/.pre-commit-config.yaml b/.pre-commit-config.yaml",), [".pre-commit-config.yaml"], id="the pre-commit config"),
        pytest.param(("a/.github/workflows/pr-checks.yml b/.github/workflows/pr-checks.yml",), [".github/workflows/pr-checks.yml"], id="a workflow"),
        pytest.param(("a/.github/actions/setup/action.yml b/.github/actions/setup/action.yml",), [".github/actions/setup/action.yml"], id="an action"),
        pytest.param(("a/tools/doc_scripts/x.py b/tools/doc_scripts/x.py",), ["tools/doc_scripts/x.py"], id="a tool"),
        pytest.param(("a/pyproject.toml b/pyproject.toml",), ["pyproject.toml"], id="the project dependencies"),
        pytest.param(("a/uv.lock b/uv.lock",), ["uv.lock"], id="the lock file"),
        pytest.param(("a/docs/old.md b/tools/moved.py",), ["tools/moved.py"], id="a file renamed into tools"),
        pytest.param(("a/tools/old.py b/docs/moved.md",), ["tools/old.py"], id="a file renamed out of tools"),
        pytest.param(("a/docs/x y.md b/tools/x y.md",), ["tools/x y.md"], id="a path with a space"),
        pytest.param(('"a/docs/\\303\\251.md" "b/tools/\\303\\251.py"',), ["tools/\\303\\251.py"], id="a quoted path"),
        pytest.param(("a/docs/toolsy.md b/docs/toolsy.md",), [], id="a name that only contains tools"),
    ],
)
def test_the_stop_list_names_what_a_layer_touches(headers: tuple[str, ...], expected: list[str]) -> None:
    stopped = Layer(id="0001a", slug="s", patch=b"", subject="s", authored=0, diff_headers=headers, source="series")

    assert stopped_by(stopped) == expected
