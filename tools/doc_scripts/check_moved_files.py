#!/usr/bin/env python3
"""A file that git history shows was renamed or removed isn't named by its
old name anywhere in the tree.

Outside docs/decisions/, a mention is corrected to the current name or
dropped. Inside an accepted decision revision the old name stays, since the
revision records what was true when it was written, and its first mention in
that revision carries a note: `old (renamed: new)`, `old (removed)` or
`old (removed; replaced by: new)`. A table row is a from -> to record and
needs no note.

The moves come from the whole commit history, so this needs a full clone and
checks the whole tree on every run, not only the files a change touches. In a
shallow clone the history is cut short; the check says so and passes.

Usage:
    cd tools && python3 -m doc_scripts.check_moved_files
"""

from __future__ import annotations

import posixpath
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCAN_EXTS = {".md", ".yml", ".yaml", ".py", ".sh", ".toml", ".hcl", ".j2", ".json", ".json5", ".txt", ".cfg", ".conf"}
# Tests name arbitrary files as fixtures, and may name a removed one to test its removal.
EXCLUDE_PREFIXES = ("tools/tests/",)
# Names that were once a repo file but are also the name of a file a container or role creates at run time.
IGNORED_NAMES = frozenset({"conf.yaml", "conf.yml"})

ADR_PATH_RE = re.compile(r"docs/decisions/[^/]+/[^/]+\.md")
NOTE_RE = re.compile(r"\((?:renamed|removed)\b")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def is_shallow(root: Path) -> bool:
    return git(root, "rev-parse", "--is-shallow-repository").strip() == "true"


def moved_files(root: Path) -> dict[str, str | None]:
    """Basename of every file that was renamed or deleted and is no longer
    anywhere in the tree -> the path it ended up at, or None if removed."""
    tracked = set(git(root, "ls-files").splitlines())
    tracked_names = {Path(t).name for t in tracked}
    renamed: dict[str, str] = {}
    deleted: set[str] = set()
    for line in git(root, "log", "--diff-filter=DR", "-M", "--name-status", "--format=").splitlines():
        parts = line.split("\t")
        if parts[0].startswith("R"):
            renamed.setdefault(parts[1], parts[2])
        elif parts[0] == "D":
            deleted.add(parts[1])
    moved: dict[str, str | None] = {}
    for old in sorted(renamed.keys() | deleted):
        name = Path(old).name
        if old in tracked or name in tracked_names or "." not in name or name in IGNORED_NAMES:
            continue
        dest, seen = renamed.get(old), {old}
        while dest in renamed and dest not in seen and dest not in tracked:
            seen.add(dest)
            dest = renamed[dest]
        moved.setdefault(name, dest if dest in tracked else None)
    return moved


def _noted(text: str, start: int, end: int, rel: str, tracked: set[str]) -> bool:
    """Whether a mention at [start, end) carries its note, written after the
    name or the backtick span around it, after a possessive, or after the
    link the name is the text of. A link to the file as it is now stands in
    for the note."""
    line_end = text.find("\n", end)
    tail = text[end : line_end if line_end != -1 else len(text)]
    head = text[text.rfind("\n", 0, start) + 1 : start]
    if head.count("`") % 2 == 1:
        tail = re.sub(r"^[^`]*`", "", tail)
    elif tail.startswith("`"):
        tail = tail[1:]
    link = re.match(r"(?:'s)?\]\(([^)#]*)", tail)
    if link:
        target = (Path(rel).parent / link.group(1)).as_posix()
        if posixpath.normpath(target) in tracked:
            return True
    tail = re.sub(r"^(?:'s)?(?:\]\([^)]*\))?", "", tail)
    return bool(re.match(r"\s*" + NOTE_RE.pattern, tail))


def _in_table(text: str, pos: int) -> bool:
    return text.startswith("|", text.rfind("\n", 0, pos) + 1)


def stale_mentions(root: Path, moved: dict[str, str | None]) -> list[str]:
    errors: list[str] = []
    tracked = set(git(root, "ls-files").splitlines())
    names = {name: re.compile(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-])") for name in moved}
    for rel in sorted(set(git(root, "ls-files", "--cached", "--others", "--exclude-standard").splitlines())):
        path = root / rel
        if path.suffix not in SCAN_EXTS or rel.startswith(EXCLUDE_PREFIXES) or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        is_adr = bool(ADR_PATH_RE.fullmatch(rel))
        for name, pattern in names.items():
            matches = [m for m in pattern.finditer(text) if not (is_adr and _in_table(text, m.start()))]
            if not matches:
                continue
            dest = moved[name]
            now = f"renamed to {dest}" if dest else "removed"
            if not is_adr:
                line = text.count("\n", 0, matches[0].start()) + 1
                errors.append(f"{rel}:{line}: names {name}, which was {now}; use the current name or drop the mention")
                continue
            first = matches[0]
            if not _noted(text, first.start(), first.end(), rel, tracked):
                line = text.count("\n", 0, first.start()) + 1
                errors.append(
                    f"{rel}:{line}: first mention of {name} needs a note: `{name}` (renamed: `new`), (removed) or (removed; replaced by: `new`); it was {now}"
                )
    return errors


def main() -> int:
    if is_shallow(ROOT):
        print("Shallow clone: the history needed to find renamed and removed files is missing, so this check was skipped.")
        return 0
    errors = stale_mentions(ROOT, moved_files(ROOT))
    for e in errors:
        print(f"::error::{e}")
    if errors:
        print(f"\n{len(errors)} mention(s) of renamed or removed files.", file=sys.stderr)
        return 1
    print("No file is named by an old name.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
