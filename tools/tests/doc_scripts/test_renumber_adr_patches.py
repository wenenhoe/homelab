"""Unit tests for renumber_adr_patches.py - moving the lineages a patch series adds off a number
the tree already holds. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from doc_scripts import renumber_adr_patches as renumber

HEADER = (
    "From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\n"
    "From: T <t@t.t>\n"
    "Date: Mon, 19 Oct 2026 10:00:00 +0800\n"
    "Subject: [PATCH] {subject}\n\n"
    "---\n"
)


def lineage_patch(number: str, slug: str, body: tuple[str, ...] = (), subject: str | None = None) -> str:
    """A patch that creates `revision-000.md` of a lineage, as `git format-patch` writes it."""
    path = f"docs/decisions/{number}-{slug}/revision-000.md"
    lines = [f"id: ADR-{number}", f"# {number}. Title", *body]
    added = "".join(f"+{line}\n" for line in lines)
    return (
        HEADER.format(subject=subject or f"docs(decisions): add {slug}")
        + f"diff --git a/{path} b/{path}\nnew file mode 100644\nindex 0000000..1111111\n--- /dev/null\n+++ b/{path}\n"
        + f"@@ -0,0 +1,{len(lines)} @@\n{added}-- \n2.43.0\n\n"
    )


def edit_patch(number: str, slug: str, context: str, added: str) -> str:
    """A patch that adds a line after `context` in an existing revision of the lineage."""
    path = f"docs/decisions/{number}-{slug}/revision-000.md"
    return (
        HEADER.format(subject=f"docs(decisions): extend {slug}")
        + f"diff --git a/{path} b/{path}\nindex 1111111..2222222 100644\n--- a/{path}\n+++ b/{path}\n"
        + f"@@ -1,1 +1,2 @@\n {context}\n+{added}\n-- \n2.43.0\n\n"
    )


@pytest.fixture
def patches(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("patches")


def hold(root: Path, *dirs: str) -> None:
    for name in dirs:
        (root / "docs" / "decisions" / name).mkdir(parents=True)


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


class TestHeldNumbers:
    def test_maps_each_lineage_directory_by_its_number(self, root):
        hold(root, "0001-a", "0089-alpha")
        assert renumber.held_numbers(root) == {"0001": "0001-a", "0089": "0089-alpha"}

    def test_files_and_other_directories_are_not_lineages(self, root):
        hold(root, "0001-a", "notes")
        (root / "docs" / "decisions" / "README.md").write_text("x", encoding="utf-8")
        assert renumber.held_numbers(root) == {"0001": "0001-a"}

    def test_a_tree_without_decisions_holds_nothing(self, root):
        assert renumber.held_numbers(root) == {}


class TestAddedLineages:
    def test_reads_the_directory_of_each_created_file(self):
        texts = {"0001.patch": lineage_patch("0089", "bravo"), "0002.patch": lineage_patch("0090", "charlie")}
        assert renumber.added_lineages(texts) == {"0089": "bravo", "0090": "charlie"}

    def test_a_file_that_is_only_edited_adds_nothing(self):
        assert renumber.added_lineages({"0001.patch": edit_patch("0089", "bravo", "id: ADR-0089", "x")}) == {}

    def test_two_directories_with_one_number_fail(self):
        texts = {"0001.patch": lineage_patch("0089", "bravo"), "0002.patch": lineage_patch("0089", "charlie")}
        with pytest.raises(SystemExit, match="adds 0089-charlie, but the series already adds 0089-bravo"):
            renumber.added_lineages(texts)


class TestFindCollisions:
    def test_a_held_number_under_another_name_collides(self):
        (collision,) = renumber.find_collisions({"0089": "0089-alpha"}, {"0089": "bravo"})
        assert (collision.number, collision.slug, collision.held_by, collision.new_number) == ("0089", "bravo", "0089-alpha", "0090")

    def test_the_held_directory_itself_is_not_a_collision(self):
        assert renumber.find_collisions({"0089": "0089-alpha"}, {"0089": "alpha"}) == []

    def test_a_free_number_is_not_a_collision(self):
        assert renumber.find_collisions({"0089": "0089-alpha"}, {"0090": "bravo"}) == []

    def test_the_new_number_skips_numbers_the_series_adds(self):
        collisions = renumber.find_collisions({"0089": "0089-alpha"}, {"0089": "bravo", "0090": "charlie"})
        assert [c.new_number for c in collisions] == ["0091"]

    def test_several_collisions_get_consecutive_numbers(self):
        collisions = renumber.find_collisions({"0088": "0088-x", "0089": "0089-y"}, {"0088": "a", "0089": "b"})
        assert [(c.number, c.new_number) for c in collisions] == [("0088", "0090"), ("0089", "0091")]


class TestRewrite:
    COLLISION = renumber.Collision("0089", "bravo", "0089-alpha", "0090")

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            pytest.param("+++ b/docs/decisions/0089-bravo/revision-000.md\n", "+++ b/docs/decisions/0090-bravo/revision-000.md\n", id="directory-name"),
            pytest.param("+id: ADR-0089\n", "+id: ADR-0090\n", id="frontmatter-id"),
            pytest.param("+related: [ADR-0089]\n", "+related: [ADR-0090]\n", id="id-in-a-list"),
            pytest.param("+decision: ADR-0089/2\n", "+decision: ADR-0090/2\n", id="id-with-a-revision"),
            pytest.param("+See ADR 0089 for it.\n", "+See ADR 0090 for it.\n", id="id-with-a-space"),
            pytest.param("+# 0089. Title\n", "+# 0090. Title\n", id="heading-of-an-added-line"),
            pytest.param(" # 0089. Title\n", " # 0090. Title\n", id="heading-of-a-context-line"),
            pytest.param(
                "+| [0089](0089-bravo/revision-000.md) |\n",
                "+| [0090](0090-bravo/revision-000.md) |\n",
                id="index-link-and-its-target",
            ),
            pytest.param(
                "+| [0089](decisions/0089-bravo/revision-000.md) |\n",
                "+| [0090](decisions/0090-bravo/revision-000.md) |\n",
                id="index-link-from-project-planning",
            ),
            pytest.param("Subject: [PATCH] docs: add ADR-0089\n", "Subject: [PATCH] docs: add ADR-0090\n", id="commit-subject"),
        ],
    )
    def test_the_lineage_number_is_replaced(self, text, expected):
        assert renumber.rewrite(text, [self.COLLISION])[0] == expected

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("+listen on port 0089\n", id="bare-number"),
            pytest.param("+docs/decisions/0089-other/revision-000.md\n", id="another-lineage-with-the-number"),
            pytest.param("+docs/decisions/0089-bravo-two/revision-000.md\n", id="longer-slug"),
            pytest.param("+docs/decisions/10089-bravo/revision-000.md\n", id="longer-number"),
            pytest.param("+docs/decisions/x-0089-bravo/revision-000.md\n", id="prefixed-name"),
            pytest.param("+MYADR-0089 and 0089ADR 0089x\n", id="id-inside-a-longer-word"),
            pytest.param("+ADR-00890 and ADR-0189\n", id="longer-or-different-id"),
            pytest.param("+[0089](https://example.com)\n", id="link-to-something-else"),
            pytest.param("+# 0089 without a dot\n", id="heading-without-the-dot"),
            pytest.param("x# 0089. Title\n", id="heading-with-no-diff-prefix"),
        ],
    )
    def test_anything_else_is_left_alone(self, text):
        assert renumber.rewrite(text, [self.COLLISION]) == (text, 0)

    def test_counts_every_replacement(self):
        text = "+id: ADR-0089\n+# 0089. T\n+See ADR 0089.\n"
        assert renumber.rewrite(text, [self.COLLISION])[1] == 3


class TestMain:
    def run(self, root, patches, *args, capsys):
        code = renumber.main([*(str(p) for p in patches), "--root", str(root), *args])
        return code, capsys.readouterr().out

    def test_writes_the_series_with_the_lineage_moved(self, root, patches, capsys):
        hold(root, "0089-alpha")
        first = write(patches, "0001-add-bravo.patch", lineage_patch("0089", "bravo", ("See ADR-0089.",), subject="docs: add ADR-0089"))
        second = write(patches, "0002-extend-bravo.patch", edit_patch("0089", "bravo", "id: ADR-0089", "Cross-reference."))

        code, out = self.run(root, [first, second], capsys=capsys)

        assert code == 0
        moved = (patches / "renumbered" / "0001-add-bravo.patch").read_text(encoding="utf-8")
        assert "+++ b/docs/decisions/0090-bravo/revision-000.md" in moved
        assert "+id: ADR-0090" in moved
        assert "+# 0090. Title" in moved
        assert "+See ADR-0090." in moved
        assert "Subject: [PATCH] docs: add ADR-0090" in moved
        followup = (patches / "renumbered" / "0002-extend-bravo.patch").read_text(encoding="utf-8")
        assert "+++ b/docs/decisions/0090-bravo/revision-000.md" in followup
        assert " id: ADR-0090\n" in followup
        assert "ADR 0089 (bravo) is held by 0089-alpha; now 0090" in out

    def test_the_originals_are_not_modified(self, root, patches, capsys):
        hold(root, "0089-alpha")
        original = lineage_patch("0089", "bravo")
        patch = write(patches, "0001-add-bravo.patch", original)

        self.run(root, [patch], capsys=capsys)

        assert patch.read_text(encoding="utf-8") == original

    def test_a_patch_that_names_no_collision_is_copied_as_it_was(self, root, patches, capsys):
        hold(root, "0089-alpha")
        first = write(patches, "0001-add-bravo.patch", lineage_patch("0089", "bravo"))
        unrelated = write(patches, "0002-unrelated.patch", edit_patch("0013", "secret-storage", "id: ADR-0013", "A line."))

        self.run(root, [first, unrelated], capsys=capsys)

        assert (patches / "renumbered" / "0002-unrelated.patch").read_text(encoding="utf-8") == unrelated.read_text(encoding="utf-8")

    def test_the_output_is_a_series_with_nothing_left_to_renumber(self, root, patches, capsys):
        hold(root, "0089-alpha")
        patch = write(patches, "0001-add-bravo.patch", lineage_patch("0089", "bravo"))
        self.run(root, [patch], capsys=capsys)

        code, out = self.run(root, [patches / "renumbered" / "0001-add-bravo.patch"], capsys=capsys)

        assert code == 0
        assert "No lineage the series adds shares a number" in out

    def test_no_collision_writes_nothing(self, root, patches, capsys):
        hold(root, "0089-alpha")
        patch = write(patches, "0001-add-bravo.patch", lineage_patch("0090", "bravo"))

        code, out = self.run(root, [patch], capsys=capsys)

        assert code == 0
        assert "No lineage the series adds shares a number" in out
        assert not (patches / "renumbered").exists()

    def test_check_reports_the_collision_and_writes_nothing(self, root, patches, capsys):
        hold(root, "0089-alpha")
        patch = write(patches, "0001-add-bravo.patch", lineage_patch("0089", "bravo"))

        code, out = self.run(root, [patch], "--check", capsys=capsys)

        assert code == 1
        assert "ADR 0089 (bravo) is held by 0089-alpha; would become 0090" in out
        assert not (patches / "renumbered").exists()

    def test_out_names_the_directory_written(self, root, patches, tmp_path_factory, capsys):
        hold(root, "0089-alpha")
        patch = write(patches, "0001-add-bravo.patch", lineage_patch("0089", "bravo"))
        out_dir = tmp_path_factory.mktemp("fixed")

        self.run(root, [patch], "--out", str(out_dir), capsys=capsys)

        assert "+id: ADR-0090" in (out_dir / "0001-add-bravo.patch").read_text(encoding="utf-8")

    def test_out_may_not_be_the_directory_of_the_patches(self, root, patches, capsys):
        hold(root, "0089-alpha")
        patch = write(patches, "0001-add-bravo.patch", lineage_patch("0089", "bravo"))

        with pytest.raises(SystemExit) as raised:
            renumber.main([str(patch), "--root", str(root), "--out", str(patches)])

        assert raised.value.code == 2
        assert "would overwrite the originals" in capsys.readouterr().err

    def test_two_patches_may_not_share_a_file_name(self, root, patches, tmp_path_factory, capsys):
        other = tmp_path_factory.mktemp("other")
        first = write(patches, "0001-a.patch", lineage_patch("0090", "bravo"))
        second = write(other, "0001-a.patch", lineage_patch("0091", "charlie"))

        with pytest.raises(SystemExit) as raised:
            renumber.main([str(first), str(second), "--root", str(root)])

        assert raised.value.code == 2
        assert "share a file name" in capsys.readouterr().err
