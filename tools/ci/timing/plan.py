"""Names the roles whose Molecule scenarios have to be timed again.

A role is timed again when it has no measurement, when its fingerprint
(`ci.timing.fingerprint`) differs from the measured one, or when the
measurement is older than --max-age-days, which catches a slower or faster
runner that no file in the repo explains. --force names every role.

Usage (from tools/): python -m ci.timing.plan --state FILE [--max-age-days N] [--force]
Writes roles=<json array> to $GITHUB_OUTPUT (stdout if unset).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from ci.output import write_output
from ci.scope.molecule_scope import REPO_ROOT, ScopeError
from ci.timing import fingerprint, state

DEFAULT_MAX_AGE_DAYS = 90


def reason(entry: dict | None, current: str, today: date, max_age_days: int) -> str | None:
    """Why a role needs timing again, or None when its measurement still holds."""
    if not isinstance(entry, dict):
        return "not measured"
    if entry.get("fingerprint") != current:
        return "its files changed"
    try:
        age = (today - date.fromisoformat(entry["measured"])).days
    except KeyError, TypeError, ValueError:
        return "measurement has no valid date"
    if age > max_age_days:
        return f"measured {age} days ago"
    return None


def stale_roles(recorded: dict, current: dict[str, str], today: date, max_age_days: int, force: bool = False) -> dict[str, str]:
    """Role -> why, for each role to time again."""
    out = {}
    for role, digest in sorted(current.items()):
        why = "forced" if force else reason(recorded["roles"].get(role), digest, today, max_age_days)
        if why:
            out[role] = why
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        current = fingerprint.fingerprints(REPO_ROOT)
    except (ScopeError, fingerprint.FingerprintError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    due = stale_roles(state.load(args.state), current, date.today(), args.max_age_days, args.force)
    for role, why in due.items():
        print(f"{role}: {why}")
    print(f"Timing {len(due)} of {len(current)} roles")
    write_output("roles", json.dumps(list(due), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
