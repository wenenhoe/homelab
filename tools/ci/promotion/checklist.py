#!/usr/bin/env python3
"""Writes the promotion checklist into a pull request description.

The checklist sits between two markers in the description. Everything outside
them is the maintainer's and is never touched; a description without the
markers gets the block appended. A box the maintainer ticked stays ticked
while its command is still on the list. The checklist is advisory: it asks
for commands and gates nothing.

The changed paths and the current description come from files, and the new
description goes to a file, so a workflow holds the GitHub calls and this
module holds the rules. Paths come from a branch anyone with push access can
name, so only plain ones are printed back.

Usage (from tools/): python -m ci.promotion.checklist --paths FILE --body FILE --out FILE
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ci.promotion.rules import RULES, Item, Rule, checklist

START = "<!-- promotion-checklist:start -->"
END = "<!-- promotion-checklist:end -->"
SHOWN = 5
_PLAIN = re.compile(r"[A-Za-z0-9_./@+=,:~-]+")
_TICKED = re.compile(r"^- \[[xX]\] `([^`\n]+)`", re.MULTILINE)


class MarkerError(Exception):
    """The description's markers are not a start followed by an end."""


def _named(paths: tuple[str, ...]) -> str:
    plain = [p for p in paths if _PLAIN.fullmatch(p)]
    text = ", ".join(f"`{p}`" for p in plain[:SHOWN])
    rest = len(paths) - min(len(plain), SHOWN)
    return f"{text} and {rest} more" if text and rest else text or f"{rest} changed paths"


def render(items: list[Item], ticked: frozenset[str] = frozenset()) -> str:
    lines = [START, "## Run after merging", ""]
    if items:
        lines.append("The CD agent deploys `main` by itself; this lists what it does not. It is advice and never blocks a merge.")
        lines.append("")
        for item in items:
            box = "x" if item.rule.command in ticked else " "
            lines.append(f"- [{box}] `{item.rule.command}` in {item.rule.where} ({_named(item.paths)})")
    else:
        lines.append("Nothing to run by hand: the CD agent deploys what this changes.")
    lines.append(END)
    return "\n".join(lines)


def splice(body: str, items: list[Item]) -> str:
    start, end = body.find(START), body.find(END)
    if (start == -1) != (end == -1) or body.count(START) > 1 or body.count(END) > 1 or (start != -1 and end < start):
        raise MarkerError(f"the description needs one {START} followed by one {END}, or neither")
    if start == -1:
        block = render(items)
        return f"{body.rstrip()}\n\n{block}\n" if body.strip() else f"{block}\n"
    end += len(END)
    ticked = frozenset(_TICKED.findall(body[start:end]))
    return body[:start] + render(items, ticked) + body[end:]


def main(argv: list[str] | None = None, rules: tuple[Rule, ...] = RULES) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--paths", type=Path, required=True, help="changed paths, one per line")
    parser.add_argument("--body", type=Path, required=True, help="the current description")
    parser.add_argument("--out", type=Path, required=True, help="where the new description goes")
    args = parser.parse_args(argv)
    changed = [line for line in args.paths.read_text().splitlines() if line]
    try:
        args.out.write_text(splice(args.body.read_text(), checklist(changed, rules)))
    except MarkerError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
