"""Tests for ci.scope.molecule_shards.

The table is checked against scenarios on disk, so the rules are exercised on
small temporary trees and the real table is checked against the real tree.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ci.scope import molecule_shards as ms


def scenario(root: Path, role: str, name: str) -> None:
    path = root / ms.ROLES_DIR / role / "molecule" / name / "molecule.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n")


def table(root: Path, text: str) -> None:
    path = root / ms.TABLE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def tree(root):
    for name in ("a", "b", "c"):
        scenario(root, "big", name)
    scenario(root, "small", "default")
    table(root, "big:\n  - [a, b]\n  - [c]\n")
    return root


class TestLoadTable:
    @pytest.mark.parametrize(
        "text",
        ["big:\n  - [a, b]\n", "big: [a, b]\n", "big:\n  - [a]\n  - []\n", "big:\n  - [a]\n  - [1]\n"],
        ids=["one shard", "not a list of lists", "empty shard", "non-string scenario"],
    )
    def test_a_malformed_entry_is_an_error(self, root, text):
        table(root, text)
        with pytest.raises(ms.ShardError, match="big must list at least two shards"):
            ms.load_table(root)

    def test_an_empty_file_is_an_empty_table(self, root):
        table(root, "# nothing split\n")
        assert ms.load_table(root) == {}


class TestLegs:
    def test_a_split_role_becomes_one_leg_per_shard_and_the_rest_run_whole(self, tree):
        assert ms.legs(["small", "big"], ms.load_table(tree), tree) == [
            {"name": "big-1", "role": "big", "scenarios": "a b"},
            {"name": "big-2", "role": "big", "scenarios": "c"},
            {"name": "small", "role": "small", "scenarios": ""},
        ]

    def test_a_split_role_that_is_not_queued_adds_nothing(self, tree):
        assert ms.legs(["small"], ms.load_table(tree), tree) == [{"name": "small", "role": "small", "scenarios": ""}]

    def test_no_roles_means_no_legs(self, tree):
        assert ms.legs([], ms.load_table(tree), tree) == []

    def test_split_roles_follow_table_order_not_the_order_they_were_queued(self, tree):
        scenario(tree, "other", "x")
        scenario(tree, "other", "y")
        table(tree, "other:\n  - [x]\n  - [y]\nbig:\n  - [a, b]\n  - [c]\n")
        names = [leg["name"] for leg in ms.legs(["big", "other"], ms.load_table(tree), tree)]
        assert names == ["other-1", "other-2", "big-1", "big-2"]

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("big:\n  - [a, b]\n  - [b, c]\n", "listed more than once: b"),
            ("big:\n  - [a]\n  - [b]\n", "in no shard (they would never run): c"),
            ("big:\n  - [a, b, c]\n  - [gone]\n", "no such scenario: gone"),
            ("missing:\n  - [a]\n  - [b]\n", "the role has no Molecule scenarios"),
        ],
        ids=["duplicate", "unlisted", "stale", "no such role"],
    )
    def test_a_table_that_disagrees_with_the_disk_is_an_error(self, tree, text, message):
        table(tree, text)
        role = next(iter(ms.load_table(tree)))
        with pytest.raises(ms.ShardError, match=message.replace("(", r"\(").replace(")", r"\)")):
            ms.legs([role], ms.load_table(tree), tree)

    def test_only_queued_roles_are_checked_against_the_disk(self, tree):
        table(tree, "big:\n  - [a]\n  - [b]\n")  # c is in no shard
        assert ms.legs(["small"], ms.load_table(tree), tree) == [{"name": "small", "role": "small", "scenarios": ""}]


class TestMain:
    def test_writes_the_legs_for_the_queued_roles(self, tree, monkeypatch, capsys):
        monkeypatch.setattr(ms, "REPO_ROOT", tree)
        monkeypatch.setenv("ROLES", '["big","small"]')
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        assert ms.main() == 0
        out = capsys.readouterr().out
        written = json.loads(out.splitlines()[-1].removeprefix("shards="))
        assert [leg["name"] for leg in written] == ["big-1", "big-2", "small"]

    @pytest.mark.parametrize("roles", [None, "not json"])
    def test_missing_or_malformed_roles_fail(self, tree, monkeypatch, roles):
        monkeypatch.setattr(ms, "REPO_ROOT", tree)
        monkeypatch.delenv("ROLES", raising=False)
        if roles is not None:
            monkeypatch.setenv("ROLES", roles)
        assert ms.main() == 1

    def test_a_table_mismatch_fails_with_an_error_annotation(self, tree, monkeypatch, capsys):
        table(tree, "big:\n  - [a]\n  - [b]\n")
        monkeypatch.setattr(ms, "REPO_ROOT", tree)
        monkeypatch.setenv("ROLES", '["big"]')
        assert ms.main() == 1
        assert "::error::" in capsys.readouterr().err


class TestRealTable:
    """The committed table against the committed tree: the check detect-changes runs, without needing a PR that queues the role."""

    REAL = ms.load_table(ms.REPO_ROOT)

    @pytest.mark.parametrize("role", sorted(REAL))
    def test_every_scenario_of_a_split_role_is_in_exactly_one_shard(self, role):
        ms.check_role(ms.REPO_ROOT, role, self.REAL[role])
