#!/usr/bin/env python3
"""Turns the roles a PR must test into the legs of pr-checks.yml's molecule job.

A role runs as one leg with every scenario unless .github/molecule-shards.yml
splits it. The table is checked against the scenarios on disk every time a
split role is queued: a scenario missing from it would silently never run, one
listed twice would run twice, and one that no longer exists would fail late.
Any mismatch is an error here instead.

Each leg is {name, role, scenarios}: `scenarios` is the space-separated list a
shard runs, empty for a whole role. Legs of split roles come first, in table
order. Actions doesn't promise to start matrix jobs in that order, so it only
makes the output stable.

Usage (from tools/): ROLES='["compose","apt"]' python -m ci.scope.molecule_shards
Writes shards=<json array> to $GITHUB_OUTPUT (stdout if unset).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

from ci.output import write_output

REPO_ROOT = Path(__file__).resolve().parents[3]
TABLE = ".github/molecule-shards.yml"
ROLES_DIR = "ansible/roles"


class ShardError(Exception):
    """The shard table disagrees with the repository."""


def load_table(root: Path) -> dict[str, list[list[str]]]:
    table = yaml.safe_load((root / TABLE).read_text()) or {}
    for role, shards in table.items():
        if not isinstance(shards, list) or len(shards) < 2 or not all(isinstance(s, list) and s and all(isinstance(n, str) for n in s) for s in shards):
            raise ShardError(f"{TABLE}: {role} must list at least two shards, each a non-empty list of scenario names")
    return table


def scenarios_on_disk(root: Path, role: str) -> set[str]:
    return {path.parent.name for path in (root / ROLES_DIR / role / "molecule").glob("*/molecule.yml")}


def check_role(root: Path, role: str, shards: list[list[str]]) -> None:
    listed = [name for shard in shards for name in shard]
    on_disk = scenarios_on_disk(root, role)
    problems = []
    if on_disk == set():
        problems.append("the role has no Molecule scenarios")
    if duplicated := sorted({n for n in listed if listed.count(n) > 1}):
        problems.append(f"listed more than once: {', '.join(duplicated)}")
    if unlisted := sorted(on_disk - set(listed)):
        problems.append(f"in no shard (they would never run): {', '.join(unlisted)}")
    if gone := sorted(set(listed) - on_disk):
        problems.append(f"no such scenario: {', '.join(gone)}")
    if problems:
        raise ShardError(f"{TABLE}: {role}: " + "; ".join(problems))


def legs(roles: list[str], table: dict[str, list[list[str]]], root: Path) -> list[dict[str, str]]:
    out = []
    for role, shards in table.items():
        if role not in roles:
            continue
        check_role(root, role, shards)
        out += [{"name": f"{role}-{i}", "role": role, "scenarios": " ".join(shard)} for i, shard in enumerate(shards, start=1)]
    out += [{"name": role, "role": role, "scenarios": ""} for role in roles if role not in table]
    return out


def main() -> int:
    try:
        roles = json.loads(os.environ["ROLES"])
        result = legs(roles, load_table(REPO_ROOT), REPO_ROOT)
    except (KeyError, json.JSONDecodeError) as exc:
        print(f"::error::ROLES must hold the JSON list of roles to test ({exc!r})", file=sys.stderr)
        return 1
    except ShardError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    print("\n".join(f"{leg['name']}: {leg['scenarios'] or 'every scenario'}" for leg in result))
    write_output("shards", json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
