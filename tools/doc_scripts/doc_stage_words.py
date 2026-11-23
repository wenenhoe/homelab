"""A doc or a comment that links a project does not name that project's stage.

`AGENTS.md` keeps a project's stage, phase and track out of everything but the
project doc: the vocabulary is deleted with the project, and a leftover reads as
work still pending. A stage word alone proves nothing, since a playbook has
stages of its own, so a unit of text is judged only when it also names a project
by a link to its doc or by its id. A unit is a paragraph, a list item or a table
row. Pure functions returning error strings, used by check_doc_drift.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from doc_scripts.doc_frontmatter import GENERATED_VIEWS, ROOT

# "Stage 1", "stages 2", "Phase A", "Track B": a stage word, then a number or a capital letter, so "stage a change" is not one.
STAGE_WORD_RE = re.compile(r"\b(?:[Ss]tage|[Pp]hase|[Tt]rack)s?\s+(?:\d+\b|[A-Z]\b)")
PROJECT_NAME_RE = re.compile(r"projects/[\w-]+\.md|\bPROJ-[\w-]+")

# Places that own the vocabulary or list it by design: the project docs, the decisions, the explorations and the generated views.
SKIP_PREFIXES = ("docs/projects/", "docs/decisions/", "docs/explorations/", "tools/tests/")
SCAN_EXTS = {".md", ".yml", ".yaml", ".py", ".sh", ".toml", ".hcl", ".j2"}
SCAN_SKIP_DIRS = {".git", "node_modules", ".venv", "vendor"}

_BLOCK_START_RE = re.compile(r"\s*(?:[-*+]\s|\d+[.)]\s|\|)")


def _units(text: str) -> list[tuple[int, str]]:
    """(first line number, text) of each paragraph, list item and table row."""
    units: list[tuple[int, list[str]]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            units.append((number, []))
        elif not units or not units[-1][1] or _BLOCK_START_RE.match(line):
            units.append((number, [line]))
        else:
            units[-1][1].append(line)
    return [(number, " ".join(lines)) for number, lines in units if lines]


def stage_word_errors(root: Path = ROOT) -> list[str]:
    errors = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix not in SCAN_EXTS or any(part in SCAN_SKIP_DIRS for part in f.parts):
            continue
        rel = f.relative_to(root).as_posix()
        if rel.startswith(SKIP_PREFIXES) or rel in GENERATED_VIEWS:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if not (STAGE_WORD_RE.search(text) and PROJECT_NAME_RE.search(text)):
            continue
        for number, unit in _units(text):
            if STAGE_WORD_RE.search(unit) and PROJECT_NAME_RE.search(unit):
                errors.append(
                    f"{rel}:{number}: names a project and one of its stages. Stage, phase and track vocabulary belongs to "
                    "the project doc and is deleted with it; say what the project adds, not which stage adds it"
                )
    return errors
