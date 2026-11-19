"""Reading a series file and putting its layers in landing order."""

from __future__ import annotations

import pytest
from _series_repo import Author, series_file
from land_series.manifest import Layer, SeriesError, group_pulls, order_layers, parse_base, parse_series


def layer(layer_id: str, slug: str | None = None, source: str = "series") -> Layer:
    return Layer(id=layer_id, slug=slug or f"slug-{layer_id[:4]}", patch=b"", subject="s", authored=0, source=source)


def test_each_layer_carries_its_slug_subject_and_date(author: Author) -> None:
    first = author.patch("docs: add a note", {"docs/note.md": "one\n"})
    second = author.patch("fix: tidy the note", {"docs/note.md": "two\n", "docs/other.md": "x\n"})
    layers = parse_series(series_file([("0001a first-note", first), ("0001b tidy-note", second)]))

    assert [(item.id, item.slug) for item in layers] == [("0001a", "first-note"), ("0001b", "tidy-note")]
    assert [item.subject for item in layers] == ["docs: add a note", "fix: tidy the note"]
    assert layers[1].authored - layers[0].authored == 60
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
        pytest.param("0001a\n", "a patch id and a branch slug", id="no slug"),
        pytest.param("0001a one two\n", "a patch id and a branch slug", id="a third word"),
    ],
)
def test_a_malformed_manifest_names_the_problem(author: Author, manifest: str, message: str) -> None:
    patch = author.patch("docs: a", {"a.txt": "a\n"})

    with pytest.raises(SeriesError, match=message):
        parse_series(manifest.encode() + b"\n" + patch)


def test_a_file_with_no_patches_is_refused() -> None:
    with pytest.raises(SeriesError, match="no patches"):
        parse_series(b"0001a one\n")


def test_commits_with_one_number_make_one_pull_request_in_letter_order() -> None:
    pulls = group_pulls(order_layers([layer("0002a"), layer("0001b"), layer("0001a"), layer("0001c")]))

    assert [(pull.number, pull.slug, [item.id for item in pull.layers]) for pull in pulls] == [
        ("0001", "slug-0001", ["0001a", "0001b", "0001c"]),
        ("0002", "slug-0002", ["0002a"]),
    ]
    assert pulls[0].title == "s"


def test_layers_from_several_files_land_in_id_order() -> None:
    ordered = order_layers([layer("0002a"), layer("0001b"), layer("0001a")])

    assert [item.id for item in ordered] == ["0001a", "0001b", "0002a"]


@pytest.mark.parametrize(
    ("layers", "message"),
    [
        pytest.param([layer("0001a"), layer("0001a", source="b")], "0001a is listed twice", id="duplicate id"),
        pytest.param([layer("0001a", slug="same"), layer("0002a", slug="same")], "'same' is used by 0001 and 0002", id="one slug on two numbers"),
        pytest.param([layer("0001a"), layer("0001b", slug="other")], "0001 has the branch slugs 'slug-0001' and 'other'", id="two slugs on one number"),
    ],
)
def test_layers_that_cannot_be_ordered_are_refused(layers: list[Layer], message: str) -> None:
    with pytest.raises(SeriesError, match=message):
        order_layers(layers)


def with_manifest_lines(author: Author, *lines: str) -> bytes:
    return "".join(f"{line}\n" for line in lines).encode() + series_file([("0001a write-one", author.patch("docs: write one", {"a.txt": "one\n"}))])


def test_a_base_line_in_the_manifest_names_the_branch(author: Author) -> None:
    data = with_manifest_lines(author, "# a note", "#   base:   develop  ")

    assert parse_base(data) == "develop"
    assert [item.id for item in parse_series(data)] == ["0001a"]


def test_a_manifest_without_a_base_line_names_none(author: Author) -> None:
    assert parse_base(with_manifest_lines(author, "# base is not named here")) is None


def test_the_same_base_named_twice_is_one_base(author: Author) -> None:
    assert parse_base(with_manifest_lines(author, "# base: develop", "# base: develop")) == "develop"


def test_two_different_bases_in_one_manifest_are_refused(author: Author) -> None:
    with pytest.raises(SeriesError, match="more than one base"):
        parse_base(with_manifest_lines(author, "# base: develop", "# base: main"))


@pytest.mark.parametrize("line", ["# base:", "# base: two words", "# base: -x", "# base: a;b"])
def test_a_base_line_that_is_not_a_branch_name_is_refused(author: Author, line: str) -> None:
    with pytest.raises(SeriesError, match="is not a branch name"):
        parse_base(with_manifest_lines(author, line))


def test_a_base_line_inside_a_patch_is_not_read(author: Author) -> None:
    patch = author.patch("docs: note", {"a.txt": "# base: develop\n"})

    assert parse_base(series_file([("0001a write-one", patch)])) is None
