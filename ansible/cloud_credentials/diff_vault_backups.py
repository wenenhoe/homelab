#!/usr/bin/env python3
"""Compare two dump_vault_to_file_cache.py backup directories: same
set of keys, same value for each.

Built for openbao-reinit-runbook.md's step 9 - confirming a post-reinit
backup matches the pre-reinit one exactly - but takes two arbitrary
directories, so it works for any two dumps.

Never prints secret values - only filenames and match/differ/missing
status.

Usage:
    python3 diff_vault_backups.py <dir-a> <dir-b> [--ignore KEY ...]

--ignore excludes named keys from the pass/fail verdict (still
reported, under their own heading) - for a key you know is expected
to differ, e.g. one rotated between the two dumps.

Exit code 0 if identical (after excluding --ignore keys), 1 if any
unexplained difference, 2 for a usage error (bad path).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _compare(dir_a: Path, dir_b: Path, ignore: set[str]) -> int:
    names_a = {p.name for p in dir_a.iterdir() if p.is_file()}
    names_b = {p.name for p in dir_b.iterdir() if p.is_file()}

    only_a = (names_a - names_b) - ignore
    only_b = (names_b - names_a) - ignore
    common = names_a & names_b

    matches, differs = [], []
    for name in sorted(common):
        same = (dir_a / name).read_text() == (dir_b / name).read_text()
        (matches if same else differs).append(name)

    ignored_differs = [n for n in differs if n in ignore]
    real_differs = [n for n in differs if n not in ignore]
    reportable_matches = [n for n in matches if n not in ignore]

    print(f"MATCH ({len(reportable_matches)}):")
    for name in reportable_matches:
        print(f"  {name}")

    if real_differs:
        print(f"\nDIFFER ({len(real_differs)}):")
        for name in real_differs:
            print(f"  {name}")

    if only_a:
        print(f"\nOnly in {dir_a} ({len(only_a)}):")
        for name in sorted(only_a):
            print(f"  {name}")

    if only_b:
        print(f"\nOnly in {dir_b} ({len(only_b)}):")
        for name in sorted(only_b):
            print(f"  {name}")

    if ignore:
        ignored_present = ignore & (names_a | names_b)
        print(f"\nIgnored ({len(ignored_present)}):")
        for name in sorted(ignored_present):
            status = "differ" if name in ignored_differs else "match" if name in common else "missing from one side"
            print(f"  {name} ({status})")

    ok = not real_differs and not only_a and not only_b
    print(f"\n{'IDENTICAL' if ok else 'MISMATCH'}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dir_a", type=Path)
    parser.add_argument("dir_b", type=Path)
    parser.add_argument("--ignore", nargs="*", default=[], metavar="KEY")
    args = parser.parse_args()

    for d in (args.dir_a, args.dir_b):
        if not d.is_dir():
            print(f"Not a directory: {d}", file=sys.stderr)
            return 2

    return _compare(args.dir_a, args.dir_b, set(args.ignore))


if __name__ == "__main__":
    raise SystemExit(main())
