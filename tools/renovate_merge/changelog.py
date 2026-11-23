"""What a Renovate pull request description says: the updates in its table and the release notes below it."""

from __future__ import annotations

import re
from dataclasses import dataclass

CHANGE_RE = re.compile(r"`([^`]+)`\s*(?:→|->|➔)\s*`([^`]+)`")
FIRST_LINK_TEXT_RE = re.compile(r"\[([^\]]+)\]")
# A number that runs straight into letters is a digest, not a version: `4e2425f` is not version 4.
VERSION_RE = re.compile(r"[=~^<>!v ]*(\d+)(?:\.(\d+))?(?![0-9A-Za-z])")
NOTES_HEADING_RE = re.compile(r"^#{2,4}[ \t]*Release Notes[ \t]*$", re.MULTILINE)
CONFIGURATION_HEADING_RE = re.compile(r"^#{2,4}[ \t]*Configuration[ \t]*$", re.MULTILINE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
SUMMARY_RE = re.compile(r"<summary>\s*(.*?)\s*</summary>", re.DOTALL)
DETAILS_RE = re.compile(r"</?details>")
BLANK_RUN_RE = re.compile(r"\n{3,}")
# Renovate writes an invisible character after each `@` and `#` in copied notes so that they notify nobody; read as text it is noise.
ZERO_WIDTH_ENTITY = "&#8203;"

MAJOR = "major"
PRE_1_0_MINOR = "pre-1.0 minor"
OTHER = "other"


@dataclass(frozen=True)
class Update:
    name: str
    old: str
    new: str
    kind: str


def _release(version: str) -> tuple[int, int | None] | None:
    """The major and minor a version starts with, ignoring a digest pinned after `@`; None when it is not numeric, such as a bare digest."""
    found = VERSION_RE.match(version.partition("@")[0])
    if not found:
        return None
    return int(found.group(1)), None if found.group(2) is None else int(found.group(2))


def classify(old: str, new: str) -> str:
    """`major` when the first number changes, `pre-1.0 minor` when a 0.x version changes its second (semver lets that break), otherwise `other`."""
    before, after = _release(old), _release(new)
    if before is None or after is None:
        return OTHER
    if before[0] != after[0]:
        return MAJOR
    if before[0] == 0 and before[1] != after[1]:
        return PRE_1_0_MINOR
    return OTHER


def _package(row: str) -> str:
    """The package of a table row: the text of the first cell's link, or the cell itself when it has none (both occur)."""
    cell = row.split("|")[1].strip()
    link = FIRST_LINK_TEXT_RE.match(cell)
    return link.group(1) if link else cell or "?"


def updates(body: str) -> list[Update]:
    """One update per table row that shows a change from one version to another."""
    found: list[Update] = []
    for line in body.splitlines():
        change = CHANGE_RE.search(line)
        if not line.startswith("|") or not change:
            continue
        old, new = change.groups()
        found.append(Update(_package(line), old, new, classify(old, new)))
    return found


def notes(body: str) -> str:
    """The release notes section without Renovate's HTML wrapping, or an empty string when the description has none (a pin, a digest, a lockfile)."""
    start = NOTES_HEADING_RE.search(body)
    if not start:
        return ""
    rest = body[start.end() :]
    end = CONFIGURATION_HEADING_RE.search(rest)
    section = rest[: end.start()] if end else rest
    section = COMMENT_RE.sub("", section)
    section = SUMMARY_RE.sub(lambda found: f"**{' '.join(found.group(1).split())}**", section)
    section = DETAILS_RE.sub("", section)
    section = section.replace(ZERO_WIDTH_ENTITY, "")
    section = BLANK_RUN_RE.sub("\n\n", section).strip()
    return section.removesuffix("---").strip()
