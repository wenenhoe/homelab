#!/usr/bin/env python3
"""Whether a path filter of `.github/detect-changes-filters.yml` is true for a range of commits, as detect-changes decides it.

detect-changes matches the changed files against the filter's globs with dorny/paths-filter, then keeps the filter true
only if a matched file changed for real (`effective_changes`). This runs the same two steps on a local checkout, so a
replay can tell which gated jobs CI would start for a pull request without a push.

Usage (from tools/): python -m ci.scope.filter_scope [--base REV] [--head REV] <filter>
Writes <filter>=true|false to $GITHUB_OUTPUT (stdout if unset). The globs are matched as pathlib's `full_match` does, the way
tests/ci/test_layout.py reads them; the filters that use it are all plain `*` and `**` patterns.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path, PurePosixPath

import yaml

from ci.output import write_output
from ci.scope import effective_changes
from ci.scope.diff import DiffError, changed_files

REPO_ROOT = Path(__file__).resolve().parents[3]
FILTERS_FILE = ".github/detect-changes-filters.yml"


class FilterScopeError(Exception):
    """The filter cannot be read or evaluated."""


def globs_of(root: Path, name: str) -> list[str]:
    try:
        filters = yaml.safe_load((root / FILTERS_FILE).read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise FilterScopeError(f"can't read {FILTERS_FILE}: {exc}") from exc
    globs = filters.get(name) if isinstance(filters, dict) else None
    if not isinstance(globs, list) or not all(isinstance(glob, str) for glob in globs):
        raise FilterScopeError(f"{FILTERS_FILE} has no filter {name!r} that is a list of globs")
    return globs


def matched(globs: list[str], changed: list[str]) -> list[str]:
    """The changed paths that match at least one glob."""
    return [path for path in changed if any(PurePosixPath(path).full_match(glob) for glob in globs)]


def is_true(root: Path, base: str, head: str, name: str) -> bool:
    if name in effective_changes.NEVER_GATED:
        raise FilterScopeError(f"{name} is not gated on real changes: {effective_changes.NEVER_GATED[name]}")
    files = matched(globs_of(root, name), changed_files(root, base, head))
    return effective_changes.effective(root, base, head, files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("name")
    args = parser.parse_args(argv)
    try:
        write_output(args.name, str(is_true(REPO_ROOT, args.base, args.head, args.name)).lower())
    except (FilterScopeError, DiffError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
