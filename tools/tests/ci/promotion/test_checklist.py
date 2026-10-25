"""Tests for ci.promotion.checklist: the block, the splice and the command line.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
from ci.promotion import checklist as cl
from ci.promotion.rules import checklist as compute

MINE = "## Why\n\nPromote this week's updates.\n"


def items(*paths: str):
    return compute(list(paths))


class TestRender:
    def test_a_command_is_a_checkbox_with_its_place_and_paths(self):
        block = cl.render(items("uv.lock"))
        assert "- [ ] `uv sync` in the repository root on the operator host (`uv.lock`)" in block
        assert block.startswith(cl.START)
        assert block.endswith(cl.END)

    def test_nothing_to_run_says_so(self):
        assert "Nothing to run by hand" in cl.render([])

    def test_it_says_it_is_advice(self):
        assert "never blocks a merge" in cl.render(items("uv.lock"))

    def test_a_ticked_command_stays_ticked(self):
        assert "- [x] `uv sync`" in cl.render(items("uv.lock"), frozenset({"uv sync"}))

    def test_paths_are_capped_and_counted(self):
        many = [f"tofu/modules/m{i}/main.tf" for i in range(8)]
        line = next(line for line in cl.render(items(*many)).splitlines() if line.startswith("- ["))
        assert line.count("`tofu/modules/") == cl.SHOWN
        assert "and 3 more" in line

    @pytest.mark.parametrize("name", ["tofu/a`b.tf", "tofu/a b.tf", "tofu/$(x).tf", "tofu/<b>.tf"], ids=repr)
    def test_an_unusual_path_is_never_printed(self, name, subtests):
        line = next(line for line in cl.render(items(name)).splitlines() if line.startswith("- ["))
        with subtests.test("not echoed"):
            assert name not in line
        with subtests.test("still counted"):
            assert "1 changed paths" in line


class TestSplice:
    def test_a_description_without_markers_gets_the_block_appended(self, subtests):
        out = cl.splice(MINE, items("uv.lock"))
        with subtests.test("the maintainer's text is first and intact"):
            assert out.startswith(MINE.rstrip())
        with subtests.test("one block"):
            assert out.count(cl.START) == out.count(cl.END) == 1

    def test_an_empty_description_is_just_the_block(self):
        out = cl.splice("", items("uv.lock"))
        assert out.startswith(cl.START)

    def test_the_block_is_replaced_and_the_text_around_it_kept(self, subtests):
        first = cl.splice(MINE, items("uv.lock"))
        edited = "Intro I added.\n\n" + first + "\nNotes under it.\n"
        out = cl.splice(edited, items("tofu/main.tf"))
        with subtests.test("text before"):
            assert out.startswith("Intro I added.\n\n## Why")
        with subtests.test("text after"):
            assert out.endswith("\nNotes under it.\n")
        with subtests.test("the old rule is gone and the new one is there"):
            assert "`uv sync`" not in out
            assert "`tofu -chdir=tofu plan`" in out

    def test_running_again_changes_nothing(self):
        once = cl.splice(MINE, items("uv.lock"))
        assert cl.splice(once, items("uv.lock")) == once

    def test_a_ticked_box_survives_a_rerun(self):
        once = cl.splice(MINE, items("uv.lock", "tofu/main.tf"))
        ticked = once.replace("- [ ] `uv sync`", "- [x] `uv sync`")
        out = cl.splice(ticked, items("uv.lock", "tofu/main.tf", "ansible/requirements.yml"))
        assert "- [x] `uv sync`" in out
        assert "- [ ] `tofu -chdir=tofu plan`" in out

    def test_a_ticked_box_is_dropped_with_its_command(self):
        ticked = cl.splice(MINE, items("uv.lock")).replace("- [ ]", "- [x]")
        assert "uv sync" not in cl.splice(ticked, items("tofu/main.tf"))

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(f"text\n{cl.START}\nno end", id="start-only"),
            pytest.param(f"text\n{cl.END}\nno start", id="end-only"),
            pytest.param(f"{cl.END}\n{cl.START}", id="end-before-start"),
            pytest.param(f"{cl.START}\n{cl.END}\n{cl.START}\n{cl.END}", id="two-blocks"),
        ],
    )
    def test_broken_markers_are_refused_not_guessed_at(self, body):
        with pytest.raises(cl.MarkerError):
            cl.splice(body, items("uv.lock"))


class TestCommandLine:
    @pytest.fixture
    def files(self, tmp_path):
        return tmp_path / "paths.txt", tmp_path / "body.md", tmp_path / "new.md"

    def run(self, files, paths: str, body: str) -> int:
        paths_file, body_file, out_file = files
        paths_file.write_text(paths)
        body_file.write_text(body)
        return cl.main(["--paths", str(paths_file), "--body", str(body_file), "--out", str(out_file)])

    def test_it_writes_the_new_description(self, files):
        assert self.run(files, "uv.lock\ndocs/x.md\n\n", MINE) == 0
        out = files[2].read_text()
        assert out.startswith(MINE.rstrip())
        assert "`uv sync`" in out

    def test_broken_markers_fail_and_write_nothing(self, files, capsys):
        assert self.run(files, "uv.lock\n", f"{cl.START} only") == 1
        assert not files[2].exists()
        assert "::error::" in capsys.readouterr().err
