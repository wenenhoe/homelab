#!/usr/bin/env python3
"""Renumbers the decision lineages a patch series adds when the tree already holds their number.

A series written against an older main can add `docs/decisions/0089-slug/` after another series
added a different lineage numbered 0089. The directories differ, so `git am` applies both and only
`generate_doc_indexes.py` and the drift check notice. This reads the patch files, finds each lineage
the series adds whose number the tree holds under another name, and writes the series to --out with
that lineage moved to the next free number: its directory name, its `ADR-NNNN` and `ADR NNNN`
references, its `# NNNN.` heading and its index link text. Nothing else is touched, so a bare
`0089` that names something other than the lineage stays as written. The originals are never
modified: run `git am --abort`, then apply the copies.

With --check it only reports the collisions and exits 1 when there is one.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from doc_scripts.doc_frontmatter import LINEAGE_DIR_RE, ROOT

NEW_LINEAGE_FILE_RE = re.compile(r"^--- /dev/null\n\+\+\+ b/docs/decisions/(\d{4})-([a-z0-9-]+)/", re.MULTILINE)


@dataclass(frozen=True)
class Collision:
    number: str
    slug: str
    held_by: str  # the directory that already has the number
    new_number: str

    @property
    def old_dir(self) -> str:
        return f"{self.number}-{self.slug}"

    @property
    def new_dir(self) -> str:
        return f"{self.new_number}-{self.slug}"


def held_numbers(root: Path) -> dict[str, str]:
    """Lineage number -> directory name, for every lineage directory in the tree."""
    decisions = root / "docs" / "decisions"
    if not decisions.is_dir():
        return {}
    return {p.name[:4]: p.name for p in sorted(decisions.iterdir()) if p.is_dir() and LINEAGE_DIR_RE.match(p.name)}


def added_lineages(texts: dict[str, str]) -> dict[str, str]:
    """Lineage number -> slug, for every lineage directory the patches create a file in."""
    added: dict[str, str] = {}
    for name, text in texts.items():
        for number, slug in NEW_LINEAGE_FILE_RE.findall(text):
            if added.setdefault(number, slug) != slug:
                raise SystemExit(f"{name}: adds {number}-{slug}, but the series already adds {number}-{added[number]}")
    return added


def find_collisions(held: dict[str, str], added: dict[str, str]) -> list[Collision]:
    """The added lineages whose number the tree holds under another directory, each with the next number
    that neither the tree, the series nor an earlier collision uses."""
    taken = {int(n) for n in [*held, *added]}
    collisions = []
    for number, slug in sorted(added.items()):
        if number in held and held[number] != f"{number}-{slug}":
            taken.add(max(taken) + 1)
            collisions.append(Collision(number, slug, held[number], f"{max(taken):04d}"))
    return collisions


def rewrite(text: str, collisions: list[Collision]) -> tuple[str, int]:
    """`text` with each collision's number replaced, and how many replacements were made."""
    total = 0
    for c in collisions:
        steps = (
            (re.compile(rf"(?<![\w-]){re.escape(c.old_dir)}(?![\w-])"), lambda _m, c=c: c.new_dir),
            (re.compile(rf"(?<!\w)ADR([- ]){c.number}(?!\d)"), lambda m, c=c: f"ADR{m.group(1)}{c.new_number}"),
            (re.compile(rf"(?m)^([ +-]# ){c.number}(\. )"), lambda m, c=c: f"{m.group(1)}{c.new_number}{m.group(2)}"),
            (re.compile(rf"\[{c.number}\]\((?=(?:\.\./)?(?:decisions/)?{re.escape(c.new_dir)})"), lambda _m, c=c: f"[{c.new_number}]("),
        )
        for pattern, replacement in steps:
            text, count = pattern.subn(replacement, text)
            total += count
    return text, total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patches", nargs="+", type=Path, metavar="PATCH", help="the series' patch files")
    ap.add_argument("--check", action="store_true", help="report collisions and exit 1 when there is one; write nothing")
    ap.add_argument("--out", type=Path, help="directory for the rewritten series (default: renumbered/ beside the first patch)")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)

    if len({p.name for p in args.patches}) != len(args.patches):
        ap.error("two patches share a file name")
    out = args.out or args.patches[0].parent / "renumbered"
    if any(out.resolve() == p.resolve().parent for p in args.patches):
        ap.error("--out is the directory the patches are in; it would overwrite the originals")

    texts = {p.name: p.read_text(encoding="utf-8") for p in args.patches}
    collisions = find_collisions(held_numbers(args.root), added_lineages(texts))
    if not collisions:
        print("No lineage the series adds shares a number with one in the tree.")
        return 0
    for c in collisions:
        print(f"ADR {c.number} ({c.slug}) is held by {c.held_by}; {'would become' if args.check else 'now'} {c.new_number}")
    if args.check:
        return 1

    out.mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        rewritten, count = rewrite(text, collisions)
        (out / name).write_text(rewritten, encoding="utf-8")
        print(f"{name}: {count} replacements")
    print(f"Wrote {len(texts)} patches to {out}; run `git am --abort` if one is in progress, then apply them with `git am`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
