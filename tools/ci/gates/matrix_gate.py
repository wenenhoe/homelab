#!/usr/bin/env python3
"""The fixed-name required check that stands in for the matrix jobs.

A matrix job can't be marked required directly: its check names change with
the matrix, and a job whose matrix is empty is skipped, so a required check
for it would either never exist or never pass. matrix-jobs-gate depends on
those jobs, runs even when they were skipped (`if: always()`), and this
module gives its verdict on their `needs` results:

- a matrix job passes on `success` or `skipped` (skipped is what "nothing
  changed" looks like) and fails on anything else;
- every other job it depends on (`detect-changes` and the cache warmers)
  must be `success`. A matrix job also reports `skipped` when an upstream
  job failed, so only the upstream jobs can tell the two apart.

Any other result, including one this check has never seen, fails: an
unrecognised value must not count as a pass. Every failing job is listed,
and a named matrix job missing from `needs` is an error, so the two lists
in the workflow can't silently drift apart.

Reads the `needs` context as JSON from $NEEDS and the matrix jobs' names from
$MATRIX_JOBS (space-separated).

Usage (from tools/): python -m ci.gates.matrix_gate
"""

from __future__ import annotations

import json
import os
import sys

SKIPPABLE = {"success", "skipped"}


class GateError(Exception):
    """The gate's inputs are missing or malformed."""


def evaluate(needs: dict[str, dict[str, object]], matrix_jobs: list[str]) -> list[str]:
    """One message per job that should block the merge; empty means pass."""
    errors = [f"{name} is named as a matrix job but is not in `needs`" for name in matrix_jobs if name not in needs]
    for name, info in needs.items():
        result = info.get("result")
        if name in matrix_jobs:
            if result not in SKIPPABLE:
                errors.append(f"A required job did not pass ({name}: {result})")
        elif result != "success":
            errors.append(f"An upstream job did not succeed ({name}: {result})")
    return errors


def _needs_from_env() -> dict[str, dict[str, object]]:
    raw = os.environ.get("NEEDS", "").strip()
    if not raw:
        raise GateError("NEEDS is not set; pass `toJSON(needs)`")
    try:
        needs = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateError(f"NEEDS is not valid JSON: {exc}") from exc
    if not isinstance(needs, dict) or not needs or not all(isinstance(v, dict) for v in needs.values()):
        raise GateError("NEEDS must be a non-empty JSON object of job -> {result, ...}")
    return needs


def main() -> int:
    try:
        needs = _needs_from_env()
        errors = evaluate(needs, os.environ.get("MATRIX_JOBS", "").split())
    except GateError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print("Upstream jobs succeeded and no matrix job failed: " + ", ".join(f"{name}={info.get('result')}" for name, info in needs.items()))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
