"""Cloning the pinned commits, and refusing a clone that is at any other.

Run via `uv run pytest tools/tests/ -v`. The fetch runs real `git` against
local repositories.
"""

from __future__ import annotations

import pytest
from _git_repos import git
from ci.shell_tests import fetch as fm
from ci.shell_tests.pins import Pin


@pytest.fixture
def lib(remote):
    """A repository with two commits; (the first commit, the second)."""
    repo = remote.repo("o/lib")
    first = repo.commit()
    repo.tag("v1.0.0", annotated=True)
    second = repo.commit()
    return repo, first, second


class TestFetch:
    def test_the_pinned_commit_is_checked_out_not_the_branch_tip(self, remote, lib, root):
        _, first, _ = lib
        assert fm.fetch([Pin("o/lib", "v1.0.0", first)], root / "clones", remote.base) == []
        assert git(root / "clones" / "lib", "rev-parse", "HEAD") == first

    def test_the_files_of_the_pinned_commit_are_in_the_tree(self, remote, lib, root):
        _, first, _ = lib
        fm.fetch([Pin("o/lib", "v1.0.0", first)], root / "clones", remote.base)
        assert (root / "clones" / "lib" / "file.txt").read_text() == "1\n"

    def test_each_pin_gets_a_directory_named_for_its_repository(self, remote, lib, root):
        _, first, _ = lib
        other = remote.repo("p/other")
        other_commit = other.commit()
        pins = [Pin("o/lib", "v1.0.0", first), Pin("p/other", "v2.0.0", other_commit)]
        assert fm.fetch(pins, root / "clones", remote.base) == []
        assert sorted(path.name for path in (root / "clones").iterdir()) == ["lib", "other"]

    def test_a_clone_already_at_the_pin_is_accepted_and_left_alone(self, remote, lib, root):
        _, first, _ = lib
        pin = Pin("o/lib", "v1.0.0", first)
        fm.fetch([pin], root / "clones", remote.base)
        marker = root / "clones" / "lib" / "marker"
        marker.write_text("kept")
        assert (fm.fetch([pin], root / "clones", remote.base), marker.read_text()) == ([], "kept")

    def test_a_clone_at_another_commit_is_refused_and_not_replaced(self, remote, lib, root):
        _, first, second = lib
        fm.fetch([Pin("o/lib", "v1.0.0", second)], root / "clones", remote.base)
        errors = fm.fetch([Pin("o/lib", "v1.0.0", first)], root / "clones", remote.base)
        assert (errors, git(root / "clones" / "lib", "rev-parse", "HEAD")) == (
            [f"{root / 'clones' / 'lib'} is at {second}, not the pinned {first} for o/lib v1.0.0; remove it to fetch the pin"],
            second,
        )

    def test_a_directory_that_is_not_a_clone_is_refused(self, remote, lib, root):
        _, first, _ = lib
        (root / "clones" / "lib").mkdir(parents=True)
        errors = fm.fetch([Pin("o/lib", "v1.0.0", first)], root / "clones", remote.base)
        assert errors == [f"{root / 'clones' / 'lib'} is at no commit, not the pinned {first} for o/lib v1.0.0; remove it to fetch the pin"]

    def test_a_directory_inside_another_repository_is_not_read_as_that_repository(self, remote, lib, root):
        _, first, _ = lib
        outer = root / "outer"
        outer.mkdir()
        git(outer, "init", "--quiet", "-b", "main")
        (outer / "f").write_text("x")
        git(outer, "add", "f")
        git(outer, "commit", "--quiet", "-m", "outer")
        outer_head = git(outer, "rev-parse", "HEAD")
        (outer / "clones" / "lib").mkdir(parents=True)
        errors = fm.fetch([Pin("o/lib", "v1.0.0", first)], outer / "clones", remote.base)
        assert errors == [f"{outer / 'clones' / 'lib'} is at no commit, not the pinned {first} for o/lib v1.0.0; remove it to fetch the pin"]
        assert outer_head not in errors[0]

    def test_a_commit_the_repository_does_not_have_fails_and_leaves_no_directory(self, remote, lib, root):
        errors = fm.fetch([Pin("o/lib", "v1.0.0", "c" * 40)], root / "clones", remote.base)
        assert (errors, (root / "clones" / "lib").exists()) == (["o/lib v1.0.0: git fetch failed"], False)

    def test_a_failed_pin_does_not_stop_the_next_one(self, remote, lib, root):
        _, first, _ = lib
        pins = [Pin("o/lib", "v1.0.0", "c" * 40), Pin("o/lib", "v1.0.0", first)]
        errors = fm.fetch(pins, root / "clones", remote.base)
        assert (len(errors), git(root / "clones" / "lib", "rev-parse", "HEAD")) == (1, first)

    def test_a_retry_after_a_failed_fetch_starts_clean(self, remote, lib, root):
        _, first, _ = lib
        fm.fetch([Pin("o/lib", "v1.0.0", "c" * 40)], root / "clones", remote.base)
        assert fm.fetch([Pin("o/lib", "v1.0.0", first)], root / "clones", remote.base) == []

    def test_a_head_that_is_not_the_pin_after_a_successful_fetch_is_refused(self, remote, lib, root):
        _, first, second = lib

        def fetch_the_wrong_commit(args, cwd, capture):
            if "fetch" in args:
                args = [*args[:-1], second]
            return fm.proc.run(args, cwd, capture)

        errors = fm.fetch([Pin("o/lib", "v1.0.0", first)], root / "clones", remote.base, run=fetch_the_wrong_commit)
        assert (errors, (root / "clones" / "lib").exists()) == ([f"o/lib v1.0.0: HEAD is {second}, not the pinned {first}"], False)

    def test_a_missing_git_is_one_clear_error_and_leaves_no_directory(self, remote, lib, root):
        _, first, _ = lib

        def no_git(args, cwd, capture):
            raise FileNotFoundError(args[0])

        errors = fm.fetch([Pin("o/lib", "v1.0.0", first)], root / "clones", remote.base, run=no_git)
        assert (errors, (root / "clones" / "lib").exists()) == (["git is not installed"], False)


class TestMain:
    def pinfile(self, root, sha):
        path = root / "pins.txt"
        path.write_text(f"o/lib v1.0.0 {sha}\n")
        return str(path)

    def test_it_lists_what_it_cloned_and_exits_zero(self, remote, lib, root, capsys):
        _, first, _ = lib
        code = fm.main([str(root / "clones"), "--pinfile", self.pinfile(root, first)], remote.base)
        assert (code, capsys.readouterr().out) == (0, f"lib v1.0.0 {first}\n")

    def test_a_refused_clone_exits_non_zero_with_an_annotation(self, remote, lib, root, capsys):
        _, first, second = lib
        fm.main([str(root / "clones"), "--pinfile", self.pinfile(root, second)], remote.base)
        capsys.readouterr()
        code = fm.main([str(root / "clones"), "--pinfile", self.pinfile(root, first)], remote.base)
        assert (code, capsys.readouterr().out.startswith("::error::")) == (1, True)

    def test_an_unreadable_pin_file_exits_non_zero(self, root, capsys):
        (root / "pins.txt").write_text("nonsense\n")
        code = fm.main([str(root / "clones"), "--pinfile", str(root / "pins.txt")])
        assert (code, (root / "clones").exists()) == (1, False)
