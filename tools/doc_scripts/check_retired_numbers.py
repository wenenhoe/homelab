#!/usr/bin/env python3
"""No tracked file names a decision number that was retired.

A decision lineage that is merged into another keeps its number only in the
new lineage's `former_ids`, and one that is demoted or dropped keeps it only in
`removed.md`. Neither redirects a reader, so a reference to the old number
(`ADR NNNN` in prose or a comment, `[NNNN](...)` over a link to the record it
became) names nothing. The drift check validates link targets and `related:`
entries; this reads the text — see doc_retired.py for what counts and what does
not.

A reference inside a frozen section of an `accepted` or `superseded` revision
is fixed like any other, but the commit that fixes it carries an
`Editorial-Fix: <path>` trailer, and the error says so.

It reads the whole tree on every run, needs no history, and works in a shallow
clone.

Usage:
    cd tools && python3 -m doc_scripts.check_retired_numbers
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT
from doc_scripts.doc_retired import retired_reference_errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests point this at a temp repo)")
    args = ap.parse_args(argv)
    errors = retired_reference_errors(args.root)
    for e in errors:
        print(f"::error::{e}")
    if errors:
        print(f"\n{len(errors)} reference(s) to a retired decision number.", file=sys.stderr)
        return 1
    print("No file names a retired decision number.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
