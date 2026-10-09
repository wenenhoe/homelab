#!/usr/bin/env python3
"""Which path-filter results still hold once no-op changes are set aside.

dorny/paths-filter reports a filter as matched when any changed file
matches one of its globs. For the filters gated here that is more than
the job behind them needs: a comment added to a test, or an edit to
`[tool.ruff]` in pyproject.toml, can't change what `pytest`, `uv sync
--locked` or the deploy-ordering run would do. Each gated filter's
matched files (paths-filter's `<filter>_files` output, from
`list-files: json`) are checked with semantic_diff, and the filter is
true only if at least one of them changed for real.

Filters whose consumer reads the comments themselves are refused:
ansible-lint honours `# noqa`, Trivy honours `#trivy:ignore`, and
compose files aren't eligible for the comparison at all.

Usage (from tools/): python -m ci.scope.effective_changes <base-sha> <head-sha> <filter>...
Each filter's file list is read as JSON from the environment variable
<FILTER>_FILES (upper-cased). Writes <filter>=true|false to
$GITHUB_OUTPUT (stdout if unset).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ci.output import write_output
from ci.scope import semantic_diff

REPO_ROOT = Path(__file__).resolve().parents[3]

# Filters that must never be gated: see the module docstring.
NEVER_GATED = {"ansible_lint": "ansible-lint honours # noqa", "trivy_ansible": "Trivy honours #trivy:ignore"}


class FilterError(Exception):
    """A filter can't be evaluated safely."""


def effective(root: Path, base: str, head: str, files: list[str]) -> bool:
    """True when at least one of `files` changed for real."""
    return any(not semantic_diff.is_noop_between(root, base, head, path) for path in files)


def files_from_env(name: str) -> list[str]:
    variable = f"{name.upper()}_FILES"
    raw = os.environ.get(variable)
    if raw is None or not raw.strip():
        raise FilterError(f"{variable} is not set; pass the filter's `<filter>_files` output from paths-filter (list-files: json)")
    try:
        files = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FilterError(f"{variable} is not valid JSON: {exc}") from exc
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        raise FilterError(f"{variable} must be a JSON array of paths")
    return files


def evaluate(root: Path, base: str, head: str, names: list[str]) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for name in names:
        if name in NEVER_GATED:
            raise FilterError(f"{name} can't be gated: {NEVER_GATED[name]}")
        results[name] = effective(root, base, head, files_from_env(name))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("base")
    parser.add_argument("head")
    parser.add_argument("filters", nargs="+")
    args = parser.parse_args(argv)
    try:
        results = evaluate(REPO_ROOT, args.base, args.head, args.filters)
    except FilterError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for name, value in results.items():
        write_output(name, str(value).lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
