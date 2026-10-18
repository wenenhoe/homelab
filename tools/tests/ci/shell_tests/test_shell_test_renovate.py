"""The Renovate manager that reads the pin file.

Run via `uv run pytest tools/tests/ -v`. Renovate's own matching isn't run
here: the test applies the manager's regex, which uses only syntax Python
reads the same way, to the committed pin file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from ci import json5
from ci.shell_tests import pins as pm

REPO_ROOT = Path(__file__).resolve().parents[4]
PIN_PATH = pm.PIN_FILE.relative_to(REPO_ROOT).as_posix()
_TEMPLATE_FIELD = re.compile(r"\{\{\{(\w+)\}\}\}")


def managers_for(path: str) -> list[dict]:
    config = json5.loads((REPO_ROOT / ".github/renovate.json5").read_text())
    found = []
    for manager in config["customManagers"]:
        for pattern in manager.get("managerFilePatterns", []):
            if re.search(pattern.strip("/"), path):
                found.append(manager)
    return found


def manager() -> dict:
    (only,) = managers_for(PIN_PATH)
    return only


def render(template: str, found: dict[str, str]) -> str:
    """Renovate's `{{{name}}}` fields filled for an unchanged pin: the new value and digest are the current ones."""
    fields = {"depName": found["depName"], "newValue": found["currentValue"], "newDigest": found["currentDigest"]}
    return _TEMPLATE_FIELD.sub(lambda name: fields[name.group(1)], template)


def matches(text: str) -> list[dict[str, str]]:
    """What the manager reads from `text`, a line each. Renovate's `(?<name>` group is Python's `(?P<name>`."""
    (pattern,) = manager()["matchStrings"]
    return [found.groupdict() for found in re.finditer(re.sub(r"\(\?<(\w+)>", r"(?P<\1>", pattern), text, re.MULTILINE)]


class TestRenovateManager:
    def test_exactly_one_manager_reads_the_pin_file(self):
        assert len(managers_for(PIN_PATH)) == 1

    def test_it_reads_every_pin_and_only_the_pins(self):
        read = [(found["depName"], found["currentValue"], found["currentDigest"]) for found in matches(pm.PIN_FILE.read_text())]
        assert read == [(pin.repository, pin.tag, pin.sha) for pin in pm.load()]

    @pytest.mark.parametrize("tag", ["v1.14.0", "2.2.4", "v0.3.0-rc.1"], ids=["v-prefixed", "bare", "prerelease"])
    def test_it_reads_any_tag_the_pin_parser_accepts(self, tag):
        line = f"x/one {tag} {'a' * 40}"
        assert (pm.parse(line)[0].tag, matches(line)[0]["currentValue"]) == (tag, tag)

    def test_a_bump_is_written_back_as_the_line_it_replaces(self):
        template = manager()["autoReplaceStringTemplate"]
        for line in (line for line in pm.PIN_FILE.read_text().splitlines() if line and not line.startswith("#")):
            (found,) = matches(line)
            assert render(template, found) == line

    def test_the_datasource_is_the_one_that_names_repositories_by_owner_and_name(self):
        assert manager()["datasourceTemplate"] == "github-tags"
