"""Rules for exploration docs (docs/explorations/*.md): the questions that have
no chosen solution yet (ADR 0037 revision 4). Pure functions returning error
strings, shared by check_doc_drift.py and generate_doc_indexes.py. Field-level
validation lives in doc_frontmatter.py.

An exploration ends by being deleted, so nothing durable may point at one: a
link that outlives it would dangle, and a decision that cites its own
exploration would keep a draft in the record. The generated planning view is
the one place that lists them.
"""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT, docs_in, load_lineages, read_frontmatter

# Days without a commit after which an open exploration is reported as stale.
EXPLORATION_STALE_DAYS = 60

EXPLORATION_PATH_RE = re.compile(r"docs/explorations/(?!(?:README|TEMPLATE)\.md\b)[\w.-]+\.md")
# Files that may name an exploration: the explorations themselves and the generated planning view.
MENTION_ALLOWED_PREFIX = "docs/explorations/"
MENTION_ALLOWED_FILES = {"docs/project-planning.md"}
MENTION_SCAN_EXTS = {".md", ".yml", ".yaml", ".py", ".sh", ".toml", ".hcl", ".j2"}
MENTION_SCAN_SKIP_DIRS = {".git", "node_modules", ".venv"}
# Test fixtures write explorations' paths into throwaway trees on purpose.
MENTION_SCAN_SKIP_PREFIXES = ("tools/tests/doc_scripts/",)


def load_explorations(root: Path = ROOT) -> list[tuple[Path, dict]]:
    directory = root / "docs" / "explorations"
    if not directory.is_dir():
        return []
    return [(path, read_frontmatter(path)) for path in docs_in(directory)]


def exploration_errors(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    explorations = load_explorations(root)
    lineage_ids = {lineage.id for lineage in load_lineages(root)}
    for path, fm in explorations:
        rel = path.relative_to(root)
        for related in fm.get("related", []):
            if related not in lineage_ids:
                errors.append(f"{rel}: related {related}, which isn't a lineage")
    errors.extend(_mention_errors(root))
    return errors


def _mention_errors(root: Path) -> list[str]:
    """Any file outside docs/explorations/ that writes an exploration's path."""
    errors = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix not in MENTION_SCAN_EXTS or any(part in MENTION_SCAN_SKIP_DIRS for part in f.parts):
            continue
        rel = f.relative_to(root).as_posix()
        if rel.startswith((MENTION_ALLOWED_PREFIX, *MENTION_SCAN_SKIP_PREFIXES)) or rel in MENTION_ALLOWED_FILES:
            continue
        for path in sorted(set(EXPLORATION_PATH_RE.findall(f.read_text(encoding="utf-8", errors="replace")))):
            errors.append(
                f"{rel}: names the exploration {path}. Nothing but the generated planning view refers to one, "
                "since it is deleted when it ends; state the question in words or link the decision it became"
            )
    return errors


def last_commit_date(root: Path, path: Path) -> date | None:
    """The date of the newest commit that touched `path`, or None when git does not know it."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%cs", "--", str(path.relative_to(root))],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return date.fromisoformat(out) if out else None
    except subprocess.CalledProcessError, FileNotFoundError, ValueError:
        return None


def stale_warnings(root: Path, today: date, limit: int = EXPLORATION_STALE_DAYS) -> list[str]:
    warnings = []
    for path, _ in load_explorations(root):
        changed = last_commit_date(root, path)
        if changed is not None and (today - changed).days > limit:
            warnings.append(
                f"warning: {path.relative_to(root)} has not changed for {(today - changed).days} days — settle it as a decision or a project, or drop it"
            )
    return warnings
