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
    # `⚠` is Renovate's own mark. `[!WARNING]` and `[!CAUTION]` are GitHub's alert blocks, which Renovate escapes as `\[!WARNING]`; authors
    # use them for what a user must know.
    ("warning", re.compile(r"⚠|\\?\[!(?:WARNING|CAUTION)\]")),
    ("security", re.compile(r"(?i:\bCVE-\d{4}-\d+|\bGHSA-[0-9a-z]{4}|\bsecurity (?:fix|advisory|vulnerabilit))")),
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

HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
# A section of fixes says what stopped going wrong (`no longer render blank`), the opposite of what the weaker words look for.
FIX_HEADING_RE = re.compile(r"^\W*(?:bug ?fix(?:es)?|fix(?:es|ed)?)\W*$", re.IGNORECASE)
# A `Removed` or `Deprecated` heading is a template some projects print in every release, with `Nothing` under it; it counts only when something is.
LISTING_HEADINGS = {"removed": "removal", "removal": "removal", "removals": "removal", "deprecated": "deprecation", "deprecations": "deprecation"}
LISTING_HEADING_RE = re.compile(r"^\W*(removed|removals?|deprecated|deprecations)\W*$", re.IGNORECASE)
EMPTY_ENTRY_RE = re.compile(r"^[\W_]*(?:nothing|none|n/a|no changes)[\W_]*$", re.IGNORECASE)

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
    pending: Flag | None = None  # a `Removed` or `Deprecated` heading waiting to see whether anything is listed under it
    in_fixes = False
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        heading = HEADING_RE.match(line)
        if heading:
            pending = None
            in_fixes = FIX_HEADING_RE.match(heading.group(1)) is not None
            listing = LISTING_HEADING_RE.match(heading.group(1))
            if listing:
                pending = Flag(LISTING_HEADINGS[listing.group(1).lower()], line)
                continue
        elif pending is not None:
            if EMPTY_ENTRY_RE.match(line):
                pending = None
                continue
            found.append(pending)
            pending = None
        weak_skipped = in_fixes or ROUTINE_ENTRY_RE.match(line) is not None
        for category, pattern in PATTERNS:
            if pattern.search(line) and not (weak_skipped and category not in BREAKING_CATEGORIES):
                found.append(Flag(category, line if len(line) <= MAX_LINE else f"{line[: MAX_LINE - 1]}…"))
    return found


def level(changes: list[Update], flags: list[Flag]) -> str:
    """`breaking` for a major version or a stated breaking change or warning, `notable` for anything weaker, `none` when nothing matched."""
    if any(change.kind == MAJOR for change in changes) or any(flag.category in BREAKING_CATEGORIES for flag in flags):
        return LEVEL_BREAKING
    if flags or any(change.kind == PRE_1_0_MINOR for change in changes):
        return LEVEL_NOTABLE
    return LEVEL_NONE
