"""Shared YAML-frontmatter reading + validation for
generate-doc-indexes.py and check-doc-drift.py. Not a standalone
script — schema documented in
docs/decisions/0028-doc-governance-frontmatter-and-nist-alignment.md.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# status values valid per `type`. Anything outside its type's set
# fails loudly rather than rendering/matching a raw enum value.
VALID_STATUS = {
    "adr": {"accepted", "superseded"},
    "draft-adr": {"draft", "decided"},
    "project": {"not-started", "in-progress", "done", "blocked"},
}


def read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        raise SystemExit(f"{path}: missing frontmatter")
    data = yaml.safe_load(m.group(1)) or {}
    for required in ("id", "title", "type", "status"):
        if required not in data:
            raise SystemExit(f"{path}: frontmatter missing required field '{required}'")
    doc_type = data["type"]
    if doc_type not in VALID_STATUS:
        raise SystemExit(f"{path}: unknown type '{doc_type}'")
    if data["status"] not in VALID_STATUS[doc_type]:
        raise SystemExit(f"{path}: status '{data['status']}' isn't valid for type: {doc_type} (expected one of {sorted(VALID_STATUS[doc_type])})")
    if data["status"] == "blocked" and not data.get("blocked_reason"):
        raise SystemExit(f"{path}: status: blocked needs a 'blocked_reason' field")
    return data


def docs_in(dir_path: Path) -> list[Path]:
    return sorted(p for p in dir_path.glob("*.md") if p.name not in ("README.md", "TEMPLATE.md"))
