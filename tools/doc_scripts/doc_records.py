"""Rules for service records (ADR 0100): the topic doc an `app_catalog` entry names
with `doc:`. Pure functions returning error strings, used by check_doc_drift.py.

A record has seven `##` sections in a fixed order, each filled. A section that
does not apply says so with the reason, and one whose fact is not known says
`Unknown:` and what to check, so an empty section is the only failure: absence
has to be a statement. The check proves the sections are present and filled,
not that they are true. The shape of the `doc:` value is the catalog rules' to
check (ci.gates.app_catalog_rules); this module reads whatever shape it finds
and leaves a malformed value to them.
"""

from __future__ import annotations

import re
from pathlib import Path

from utils.app_catalog import CATALOG_RELATIVE, CatalogError, load_catalog

from doc_scripts.doc_frontmatter import ROOT

DOC_KEY = "doc"
SECTIONS = ("Dependencies", "Data", "Exposure", "Threat model", "Observability", "Disaster recovery", "Lifecycle")

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


def _sections(text: str) -> list[tuple[str, list[str]]]:
    """Each `##` section of `text`: its title and the lines under it up to the next heading of level 1 or 2. Fenced lines are never headings."""
    found: list[tuple[str, list[str]]] = []
    fence: str | None = None
    for line in text.splitlines():
        marker = _FENCE_RE.match(line)
        if marker:
            if fence is None:
                fence = marker.group(1)
            elif marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
        heading = None if fence is not None or marker else _HEADING_RE.match(line)
        if heading and len(heading.group(1)) <= 2:
            found.append((heading.group(2).strip(), []) if len(heading.group(1)) == 2 else ("", []))
        elif found:
            found[-1][1].append(line)
    return found


def _has_content(lines: list[str]) -> bool:
    """Whether a section says anything: a line that is not blank and not just a heading. Fenced code counts."""
    return any(line.strip() and not _HEADING_RE.match(line) for line in lines)


def section_errors(text: str) -> list[str]:
    """What is wrong with a record's sections: missing, repeated, out of order or empty."""
    sections = _sections(text)
    positions: dict[str, int] = {}
    errors: list[str] = []
    for name in SECTIONS:
        at = [i for i, (title, _) in enumerate(sections) if title == name]
        if len(at) > 1:
            errors.append(f"has the section '{name}' more than once")
        if at:
            positions[name] = at[0]
    missing = [name for name in SECTIONS if name not in positions]
    if missing:
        errors.append(f"lacks the section(s) {', '.join(repr(name) for name in missing)}; the sections are {', '.join(SECTIONS)}")
    present = [positions[name] for name in SECTIONS if name in positions]
    if present != sorted(present):
        errors.append(f"has its sections out of order; they run {', '.join(SECTIONS)}")
    for name in SECTIONS:
        if name in positions and not _has_content(sections[positions[name]][1]):
            errors.append(f"the section '{name}' is empty; say it does not apply and why, or 'Unknown:' and what to check")
    return errors


def record_errors(root: Path = ROOT) -> list[str]:
    """Every catalog app names a record that exists and has its sections."""
    try:
        catalog = load_catalog(root / CATALOG_RELATIVE)
    except CatalogError as exc:
        return [str(exc)]
    errors: list[str] = []
    checked: set[str] = set()
    for name, app in catalog.items():
        doc = app.get(DOC_KEY)
        if doc is None:
            errors.append(
                f"{CATALOG_RELATIVE}: {name} has no `{DOC_KEY}:` naming its service record (ADR 0100). Write the record under docs/topics/ and name it"
            )
            continue
        if not isinstance(doc, str) or Path(doc).is_absolute() or ".." in Path(doc).parts or doc in checked:
            continue  # a malformed value is the catalog rules' to report; a record shared by several entries is read once
        checked.add(doc)
        path = root / doc
        if not path.is_file():
            errors.append(f"{CATALOG_RELATIVE}: {name} names {doc}, which doesn't exist")
            continue
        errors.extend(f"{doc}: {message}" for message in section_errors(path.read_text(encoding="utf-8")))
    return errors
