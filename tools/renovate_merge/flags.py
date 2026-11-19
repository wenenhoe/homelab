"""Where release notes and version numbers say an update may break something: a word search and a version comparison, not a verdict."""

from __future__ import annotations

import re
from dataclasses import dataclass

from renovate_merge.changelog import MAJOR, PRE_1_0_MINOR, Update

MAX_LINE = 200

# Case matters for BREAKING, which release notes shout, and not for the rest. A conventional-commit `feat!:` marks a breaking change by itself.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "breaking",
        re.compile(
            r"(?i:breaking[ -]change|backwards?[- ]incompatib|not backwards?[- ]compatible|incompatible change)|\bBREAKING\b|\b[a-z]+(?:\([^)\n]*\))?!:"
        ),
    ),
    ("warning", re.compile("⚠")),
    ("removal", re.compile(r"(?i:\bremov(?:e|ed|es|ing|al)\b|\bdrop(?:s|ped|ping)? (?:support|the)\b|\bno longer\b)")),
    ("deprecation", re.compile(r"(?i:deprecat)")),
    (
        "migration",
        re.compile(
            r"(?i:\bmigration (?:guide|required|steps?)\b|\bmigrate (?:to|from)\b|\baction required\b"
            r"|\bmanual(?:ly)? (?:step|update|intervention)|\brenam(?:e|ed|es)\b)"
        ),
    ),
    ("default", re.compile(r"(?i:\bdefaults? (?:to|is now|are now|has changed|changed)\b|\bnow defaults?\b|\bchanged? (?:the )?default)")),
)
BREAKING_CATEGORIES = frozenset({"breaking", "warning"})
# A changelog entry that opens like a commit of routine work (`fix: remove a stray key`, `refactor: remove a parameter`) says what the change did
# inside the project, not what a user must do; the weaker words in it are left alone. The stronger categories are never skipped.
ROUTINE_ENTRY_RE = re.compile(r"^\W*(?:\[`?[0-9a-f]{7,}`?\]\([^)]*\)\s*)?\W*(?:fix|refactor|chore|docs?|test|ci|build|perf|style)\b", re.IGNORECASE)

LEVEL_BREAKING = "breaking"
LEVEL_NOTABLE = "notable"
LEVEL_NONE = "none"
LEVEL_ORDER = (LEVEL_BREAKING, LEVEL_NOTABLE, LEVEL_NONE)


@dataclass(frozen=True)
class Flag:
    category: str
    line: str


def scan(text: str) -> list[Flag]:
    """Each line of `text` once per category it matches, cut to a readable length."""
    found: list[Flag] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        routine = ROUTINE_ENTRY_RE.match(line) is not None
        for category, pattern in PATTERNS:
            if pattern.search(line) and not (routine and category not in BREAKING_CATEGORIES):
                found.append(Flag(category, line if len(line) <= MAX_LINE else f"{line[: MAX_LINE - 1]}…"))
    return found


def level(changes: list[Update], flags: list[Flag]) -> str:
    """`breaking` for a major version or a stated breaking change or warning, `notable` for anything weaker, `none` when nothing matched."""
    if any(change.kind == MAJOR for change in changes) or any(flag.category in BREAKING_CATEGORIES for flag in flags):
        return LEVEL_BREAKING
    if flags or any(change.kind == PRE_1_0_MINOR for change in changes):
        return LEVEL_NOTABLE
    return LEVEL_NONE
