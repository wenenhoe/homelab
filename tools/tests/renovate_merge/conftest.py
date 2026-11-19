"""Fixtures for the renovate_merge tests."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from _bodies import PLAIN_NOTES, body


@dataclass
class FakeGitHub:
    state_file: Path

    def state(self) -> dict:
        return json.loads(self.state_file.read_text())

    def save(self, state: dict) -> None:
        self.state_file.write_text(json.dumps(state))

    def add_pull(
        self,
        title: str = "chore(deps): update dependency example/tool to v1.4.3",
        description: str | None = None,
        branch: str | None = None,
        sha: str | None = None,
        base: str = "maintenance",
        login: str = "app/example-renovate",
        fork: bool = False,
        checks: list[list[list[str]]] | None = None,
    ) -> int:
        """Open a pull request in the fake and return its number. Its checks default to every required check passing."""
        state = self.state()
        number = len(state["prs"]) + 1
        listed = {
            "number": number,
            "title": title,
            "url": f"https://example.test/pull/{number}",
            "body": description if description is not None else body("example/tool", "1.4.2", "1.4.3", PLAIN_NOTES),
            "headRefName": branch or f"renovate/tool-{number}",
            "headRefOid": sha or f"{number:07d}" + "a" * 33,
            "baseRefName": base,
            "isCrossRepository": fork,
            "author": {"login": login, "is_bot": True},
        }
        passing = [[name, "pass"] for name in state["required"]]
        state["prs"].append({"state": "OPEN", "listed": listed, "checks": checks or [passing]})
        self.save(state)
        return number

    def merged(self) -> list[int]:
        return self.state()["merges"]

    def calls(self) -> list[list[str]]:
        return self.state()["calls"]


@pytest.fixture
def github(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    """A fake `gh` first on PATH, requiring one check named `build`."""
    bin_dir = tmp_path_factory.mktemp("bin")
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\nexec {sys.executable} {Path(__file__).parent / "fake_gh.py"} "$@"\n')
    gh.chmod(0o755)
    state_file = tmp_path_factory.mktemp("gh-state") / "state.json"
    state_file.write_text(json.dumps({"prs": [], "required": ["build"], "logged_out": False, "merge_error": "", "merges": [], "calls": []}))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_STATE", str(state_file))
    return FakeGitHub(state_file)


@pytest.fixture
def no_sleep() -> list[float]:
    """A `sleep` that records the pauses asked for instead of waiting."""
    return []
