"""Tests for check_moved_files.py, run against throwaway git repositories.
Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from doc_scripts import check_moved_files as moved

ADR = "docs/decisions/0001-x/revision-000.md"


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.git("init", "-q")

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)

    def write(self, rel: str, text: str = "x\n") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str = "c") -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def move(self, old: str, new: str) -> None:
        (self.root / new).parent.mkdir(parents=True, exist_ok=True)
        self.git("mv", old, new)
        self.commit("move")

    def remove(self, rel: str) -> None:
        self.git("rm", "-q", rel)
        self.commit("remove")

    def errors(self) -> list[str]:
        return moved.stale_mentions(self.root, moved.moved_files(self.root))


@pytest.fixture
def repo(root: Path) -> Repo:
    return Repo(root)


class TestMovedFiles:
    def test_a_rename_maps_the_old_name_to_the_new_path(self, repo):
        repo.write("tools/old_name.py")
        repo.commit()
        repo.move("tools/old_name.py", "tools/new_name.py")
        assert moved.moved_files(repo.root) == {"old_name.py": "tools/new_name.py"}

    def test_a_removal_maps_to_none(self, repo):
        repo.write("tools/gone.py")
        repo.commit()
        repo.remove("tools/gone.py")
        assert moved.moved_files(repo.root) == {"gone.py": None}

    def test_a_chain_of_renames_ends_at_the_current_path(self, repo):
        repo.write("a.py")
        repo.commit()
        repo.move("a.py", "b.py")
        repo.move("b.py", "c.py")
        assert moved.moved_files(repo.root) == {"a.py": "c.py", "b.py": "c.py"}

    def test_a_rename_followed_by_a_removal_is_removed(self, repo):
        repo.write("a.py")
        repo.commit()
        repo.move("a.py", "b.py")
        repo.remove("b.py")
        assert moved.moved_files(repo.root) == {"a.py": None, "b.py": None}

    def test_a_name_another_tracked_file_still_has_is_not_reported(self, repo):
        repo.write("one/tasks.yaml")
        repo.write("two/tasks.yaml")
        repo.commit()
        repo.remove("one/tasks.yaml")
        assert moved.moved_files(repo.root) == {}

    def test_a_name_with_no_extension_is_not_reported(self, repo):
        repo.write("docker/Caddyfile")
        repo.commit()
        repo.remove("docker/Caddyfile")
        assert moved.moved_files(repo.root) == {}

    def test_names_of_files_created_at_run_time_are_not_reported(self, repo):
        repo.write("docker/dashy/conf.yml")
        repo.commit()
        repo.remove("docker/dashy/conf.yml")
        assert moved.moved_files(repo.root) == {}


class TestOutsideDecisions:
    @pytest.fixture(autouse=True)
    def _gone(self, repo):
        repo.write("tools/old_name.py")
        repo.write("tools/dead.py")
        repo.commit()
        repo.move("tools/old_name.py", "tools/new_name.py")
        repo.remove("tools/dead.py")

    def test_a_renamed_file_named_in_a_topic_doc_is_reported_with_its_new_path(self, repo):
        repo.write("docs/topics/a.md", "Run `old_name.py` first.\n")
        assert repo.errors() == ["docs/topics/a.md:1: names old_name.py, which was renamed to tools/new_name.py; use the current name or drop the mention"]

    def test_a_removed_file_named_in_a_comment_is_reported(self, repo):
        repo.write("tools/x.py", "x = 1\n# see dead.py\n")
        assert repo.errors() == ["tools/x.py:2: names dead.py, which was removed; use the current name or drop the mention"]

    def test_the_current_name_passes(self, repo):
        repo.write("docs/topics/a.md", "Run `new_name.py` first.\n")
        assert repo.errors() == []

    def test_a_longer_name_that_contains_the_old_one_passes(self, repo):
        repo.write("docs/topics/a.md", "`pre_old_name.py` and `old_name.pyc`.\n")
        assert repo.errors() == []

    def test_a_test_fixture_may_name_it(self, repo):
        repo.write("tools/tests/test_x.py", "PATH = 'dead.py'\n")
        assert repo.errors() == []

    def test_a_decision_note_does_not_excuse_a_topic_doc(self, repo):
        repo.write("docs/topics/a.md", "`dead.py` (removed)\n")
        assert len(repo.errors()) == 1


class TestInADecision:
    @pytest.fixture(autouse=True)
    def _gone(self, repo):
        repo.write("tools/old_name.py")
        repo.write("tools/dead.py")
        repo.commit()
        repo.move("tools/old_name.py", "tools/new_name.py")
        repo.remove("tools/dead.py")

    @pytest.mark.parametrize(
        "text",
        [
            "`old_name.py` (renamed: `new_name.py`) runs.\n",
            "`old_name.py`'s (renamed: `new_name.py`) role.\n",
            "`tools/old_name.py` (renamed: `tools/new_name.py`) runs.\n",
            "`old_name.py --flag` (renamed: `new_name.py`) runs.\n",
            "`dead.py` (removed) runs.\n",
            "`dead.py` (removed; replaced by: `new_name.py`) runs.\n",
            "[`old_name.py`](../../../tools/new_name.py) runs.\n",
        ],
    )
    def test_a_first_mention_with_its_note_passes(self, repo, text):
        repo.write(ADR, text)
        assert repo.errors() == []

    def test_a_first_mention_without_a_note_is_reported(self, repo):
        repo.write(ADR, "Intro.\n`old_name.py` runs.\n")
        errors = repo.errors()
        assert len(errors) == 1
        assert errors[0].startswith(f"{ADR}:2: first mention of old_name.py needs a note")

    def test_only_the_first_mention_needs_a_note(self, repo):
        repo.write(ADR, "`dead.py` (removed) runs, then `dead.py` again.\n")
        assert repo.errors() == []

    def test_a_note_on_a_later_mention_does_not_cover_the_first(self, repo):
        repo.write(ADR, "`dead.py` runs.\nLater `dead.py` (removed).\n")
        assert len(repo.errors()) == 1

    def test_a_table_row_is_a_record_and_needs_no_note(self, repo):
        repo.write(ADR, "| `old_name.py` | `new_name.py` |\n")
        assert repo.errors() == []

    def test_the_first_prose_mention_after_a_table_row_needs_the_note(self, repo):
        repo.write(ADR, "| `old_name.py` | `new_name.py` |\n\nThen `old_name.py` runs.\n")
        assert len(repo.errors()) == 1

    def test_a_note_for_the_neighbouring_name_does_not_cover_this_one(self, repo):
        repo.write(ADR, "`old_name.py` and `dead.py` (removed).\n")
        assert len(repo.errors()) == 1

    def test_an_unlinked_mention_is_not_excused_by_a_link_to_a_missing_file(self, repo):
        repo.write(ADR, "[`old_name.py`](../../../tools/missing.py) runs.\n")
        assert len(repo.errors()) == 1


class TestMain:
    def test_a_clean_repository_passes(self, repo, monkeypatch, capsys):
        repo.write("a.py")
        repo.commit()
        monkeypatch.setattr(moved, "ROOT", repo.root)
        assert moved.main() == 0
        assert "No file is named by an old name." in capsys.readouterr().out

    def test_a_stale_mention_fails(self, repo, monkeypatch, capsys):
        repo.write("a.py")
        repo.write("docs/a.md", "`a.py`\n")
        repo.commit()
        repo.remove("a.py")
        monkeypatch.setattr(moved, "ROOT", repo.root)
        assert moved.main() == 1
        assert "::error::docs/a.md:1: names a.py, which was removed" in capsys.readouterr().out

    def test_a_shallow_clone_is_skipped_and_says_so(self, repo, root, tmp_path_factory, monkeypatch, capsys):
        repo.write("a.py")
        repo.write("docs/a.md", "`a.py`\n")
        repo.commit()
        repo.remove("a.py")
        clone = tmp_path_factory.mktemp("clone") / "c"
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{root}", str(clone)], check=True, capture_output=True)
        monkeypatch.setattr(moved, "ROOT", clone)
        assert moved.main() == 0
        assert "Shallow clone" in capsys.readouterr().out
