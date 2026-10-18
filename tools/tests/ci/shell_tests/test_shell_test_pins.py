"""The pin file's lines and the check that each pinned tag still points at its commit.

Run via `uv run pytest tools/tests/ -v`. The check runs real `git` against
local repositories.
"""

from __future__ import annotations

import pytest
from ci import proc
from ci.shell_tests import pins as pm
from ci.shell_tests.pins import Pin, PinError

SHA = "a" * 40
OTHER = "b" * 40


def pin_for(repository: str, tag: str, sha: str) -> Pin:
    return Pin(repository, tag, sha)


class TestParse:
    def test_a_line_is_a_repository_a_tag_and_a_commit(self):
        assert pm.parse(f"bats-core/bats-core v1.14.0 {SHA}\n") == [Pin("bats-core/bats-core", "v1.14.0", SHA)]

    def test_blank_lines_and_comments_are_skipped_and_the_order_is_kept(self):
        text = f"# why\n\nx/one v1.0.0 {SHA}\n  # indented\nx/two 2.0 {OTHER}\n"
        assert [pin.name for pin in pm.parse(text)] == ["one", "two"]

    @pytest.mark.parametrize(
        ("line", "message"),
        [
            pytest.param(f"x/one v1.0.0 {SHA} extra", "got 4 field", id="a-fourth-field"),
            pytest.param("x/one v1.0.0", "got 2 field", id="no-commit"),
            pytest.param(f"one v1.0.0 {SHA}", "isn't an owner/name", id="no-owner"),
            pytest.param(f"-x/one v1.0.0 {SHA}", "isn't an owner/name", id="owner-that-looks-like-an-option"),
            pytest.param(f"x/one --upload-pack=evil {SHA}", "isn't shaped like a release tag", id="tag-that-looks-like-an-option"),
            pytest.param(f"x/one latest {SHA}", "isn't shaped like a release tag", id="tag-that-is-not-a-version"),
            pytest.param(f"x/one v1.0.0 {SHA[:7]}", "isn't a full lower-case commit SHA", id="abbreviated-commit"),
            pytest.param(f"x/one v1.0.0 {SHA.upper()}", "isn't a full lower-case commit SHA", id="upper-case-commit"),
        ],
    )
    def test_a_malformed_line_is_refused_with_its_number(self, line, message):
        with pytest.raises(PinError, match=rf"line 2: .*{message}"):
            pm.parse(f"x/ok v1.0.0 {SHA}\n{line}\n")

    def test_every_malformed_line_is_reported_not_only_the_first(self):
        with pytest.raises(PinError, match=r"line 1: .*line 2: "):
            pm.parse("one\ntwo\n")

    def test_two_repositories_with_one_name_would_share_a_clone_directory(self):
        with pytest.raises(PinError, match="two entries are named one"):
            pm.parse(f"a/one v1.0.0 {SHA}\nb/one v1.0.0 {OTHER}\n")

    @pytest.mark.parametrize("text", ["", "# only a comment\n\n"])
    def test_a_file_with_no_pins_is_refused(self, text):
        with pytest.raises(PinError, match="lists no pins"):
            pm.parse(text)


class TestLoad:
    def test_the_committed_file_pins_the_runner_and_its_two_libraries(self):
        assert {(pin.repository, pin.tag) for pin in pm.load()} == {
            ("bats-core/bats-core", "v1.14.0"),
            ("bats-core/bats-support", "v0.3.0"),
            ("bats-core/bats-assert", "v2.2.4"),
        }

    def test_a_missing_file_is_an_error_naming_it(self, root):
        with pytest.raises(PinError, match=r"can't read missing\.txt"):
            pm.load(root / "missing.txt")

    def test_a_malformed_line_is_reported_with_the_file_it_is_in(self, root):
        (root / "pins.txt").write_text("nonsense\n")
        with pytest.raises(PinError, match=r"pins\.txt: line 1"):
            pm.load(root / "pins.txt")


class TestCheck:
    def test_an_annotated_tag_is_resolved_to_its_commit_not_to_the_tag_object(self, remote):
        repo = remote.repo("o/lib")
        commit = repo.commit()
        repo.tag("v1.0.0", annotated=True)
        assert repo.tag_object("v1.0.0") != commit
        assert pm.check([pin_for("o/lib", "v1.0.0", commit)], remote.base) == []

    def test_a_lightweight_tag_is_the_commit_itself(self, remote):
        repo = remote.repo("o/lib")
        commit = repo.commit()
        repo.tag("v1.0.0", annotated=False)
        assert pm.check([pin_for("o/lib", "v1.0.0", commit)], remote.base) == []

    def test_a_pin_copied_from_the_tag_object_instead_of_the_commit_is_refused(self, remote):
        repo = remote.repo("o/lib")
        commit = repo.commit()
        repo.tag("v1.0.0", annotated=True)
        wrong = repo.tag_object("v1.0.0")
        assert pm.check([pin_for("o/lib", "v1.0.0", wrong)], remote.base) == [f"o/lib v1.0.0 points at {commit}, not the pinned {wrong}"]

    @pytest.mark.parametrize("annotated", [True, False], ids=["annotated", "lightweight"])
    def test_a_tag_moved_to_another_commit_is_refused(self, remote, annotated):
        repo = remote.repo("o/lib")
        pinned = repo.commit()
        repo.tag("v1.0.0", annotated=annotated)
        moved_to = repo.commit()
        repo.tag("v1.0.0", annotated=annotated, at=moved_to)
        assert pm.check([pin_for("o/lib", "v1.0.0", pinned)], remote.base) == [f"o/lib v1.0.0 points at {moved_to}, not the pinned {pinned}"]

    def test_a_tag_the_repository_does_not_have_is_refused(self, remote):
        repo = remote.repo("o/lib")
        commit = repo.commit()
        repo.tag("v1.0.0", annotated=True)
        assert pm.check([pin_for("o/lib", "v2.0.0", commit)], remote.base) == ["o/lib has no tag v2.0.0"]

    def test_a_branch_with_the_tags_name_is_not_the_tag(self, remote):
        repo = remote.repo("o/lib")
        commit = repo.commit()
        repo.branch("v1.0.0")
        assert pm.check([pin_for("o/lib", "v1.0.0", commit)], remote.base) == ["o/lib has no tag v1.0.0"]

    def test_a_repository_that_cannot_be_reached_fails_after_its_attempts(self, remote):
        waits: list[float] = []
        errors = pm.check([pin_for("o/absent", "v1.0.0", SHA)], remote.base, sleep=waits.append)
        assert (errors, waits) == (["o/absent v1.0.0: git ls-remote exited 128 after 3 attempts"], [2.0, 4.0])

    def test_every_pin_is_checked_and_each_failure_is_reported(self, remote):
        good = remote.repo("o/good")
        good_commit = good.commit()
        good.tag("v1.0.0", annotated=True)
        bad = remote.repo("o/bad")
        bad.commit()
        bad.tag("v1.0.0", annotated=True)
        pins = [pin_for("o/bad", "v1.0.0", SHA), pin_for("o/good", "v1.0.0", good_commit), pin_for("o/bad", "v9.0.0", SHA)]
        assert [error.split(" points")[0].split(" has")[0] for error in pm.check(pins, remote.base)] == ["o/bad v1.0.0", "o/bad"]

    def test_a_missing_git_is_one_clear_error(self, remote):
        def no_git(args, cwd, capture):
            raise FileNotFoundError(args[0])

        assert pm.check([pin_for("o/lib", "v1.0.0", SHA)], remote.base, run=no_git) == ["git is not installed"]


class TestMain:
    def pinfile(self, root, remote, *, pin_sha: str | None = None) -> str:
        repo = remote.repo("o/lib")
        commit = repo.commit()
        repo.tag("v1.0.0", annotated=True)
        path = root / "pins.txt"
        path.write_text(f"o/lib v1.0.0 {pin_sha or commit}\n")
        return str(path)

    def test_a_pin_at_its_tag_passes(self, root, remote, capsys):
        code = pm.main(["check", self.pinfile(root, remote)], remote.base)
        assert (code, capsys.readouterr().out) == (0, "1 pins: all tags point at their SHAs\n")

    def test_a_pin_off_its_tag_fails_with_an_annotation(self, root, remote, capsys):
        code = pm.main(["check", self.pinfile(root, remote, pin_sha=SHA)], remote.base)
        out = capsys.readouterr().out
        assert (code, out.splitlines()[0].startswith("::error::o/lib v1.0.0 points at "), out.splitlines()[-1]) == (1, True, "1 pins: 1 failed")

    def test_an_unreadable_pin_file_fails_before_any_git_call(self, root, capsys):
        def never(args, cwd, capture):
            raise AssertionError("git was run")

        (root / "pins.txt").write_text("nonsense\n")
        code = pm.main(["check", str(root / "pins.txt")], run=never)
        assert (code, capsys.readouterr().err.startswith("::error::pins.txt: line 1")) == (1, True)

    def test_the_default_runner_is_the_shared_one(self):
        assert pm.proc.run is proc.run
