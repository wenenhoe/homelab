"""Builders for throwaway docs/ trees used by the doc-tooling tests.
Real frontmatter, real files on disk - the code under test reads paths,
so nothing here is mocked.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[3] / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def write_doc(root: Path, rel: str, fm: dict, body: str = "# Title\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{body}", encoding="utf-8")
    return path


def revision(root: Path, lineage: str, number: int, body: str = "# Title\n", letter: str | None = None, **overrides) -> Path:
    """`lineage` is the directory name, e.g. '0013-secret-storage'. `letter` makes it a
    competing candidate (revision-NNN-x.md, with a matching `candidate:` unless overridden)."""
    fm = {
        "id": f"ADR-{lineage[:4]}",
        "revision": number,
        "type": "adr",
        "title": "Secret storage",
        "solution": f"Solution {number}",
        "summary": "Where secrets live.",
        "topic": "secrets-store",
        "status": "working",
    }
    if letter:
        fm["candidate"] = letter
    fm.update(overrides)
    suffix = f"-{letter}" if letter else ""
    return write_doc(root, f"docs/decisions/{lineage}/revision-{number:03d}{suffix}.md", fm, body)


def project(root: Path, name: str, **overrides) -> Path:
    fm = {"id": f"PROJ-{name}", "title": name, "type": "project", "status": "not-started", "summary": f"{name} summary"}
    fm.update(overrides)
    return write_doc(root, f"docs/projects/{name}.md", fm)
