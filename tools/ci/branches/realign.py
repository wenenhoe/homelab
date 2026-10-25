#!/usr/bin/env python3
"""Brings `maintenance` up to date with `main` before Renovate runs.

Renovate opens its pull requests into `maintenance`, and a pull request is only
as current as that branch. `main` moves on (a promotion, a fix straight to
production), so before each run this makes `maintenance` contain `main`:

- `maintenance` already contains `main`: nothing to do.
- `maintenance` is an ancestor of `main`: fast-forward it, so it lands exactly
  on `main`.
- the two have diverged: merge `main` into `maintenance` with a merge commit.
  A conflict aborts the merge, leaves `maintenance` as it was and fails the
  run, so the maintainer resolves it and Renovate does not run against a
  branch that is behind.

Nothing is rewritten and nothing is forced: every push is a plain push of a
commit that has the old tip as an ancestor, which the remote refuses
otherwise. Renovate treats a pull request branch as edited when someone else's
commits sit under it, so the history it builds on only ever grows. `main` is
only ever read.

Credentials come from git's own configuration (the workflow sets an
`http.extraheader`), so the token never reaches this module's arguments.

Usage (from a full-depth checkout):
    python3 -m ci.branches.realign --name NAME --email EMAIL
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ci.proc import Runner, run

REPO_ROOT = Path(__file__).resolve().parents[3]
REMOTE = "origin"
PRODUCTION = "main"
BRANCH = "maintenance"
MESSAGE = f"Merge {PRODUCTION} into {BRANCH}"


class RealignError(Exception):
    """`maintenance` could not be brought up to date with `main`."""


def _git(runner: Runner, root: Path, *args: str, capture: bool = False):
    return runner(["git", *args], root, capture)


def _fetch(runner: Runner, root: Path, branch: str) -> str:
    # No `+`: a remote-tracking ref only ever moves forward on a fresh checkout.
    if _git(runner, root, "fetch", "--no-tags", REMOTE, f"refs/heads/{branch}:refs/remotes/{REMOTE}/{branch}").returncode:
        raise RealignError(f"could not fetch {branch} from {REMOTE}; it must exist before this can run")
    result = _git(runner, root, "rev-parse", f"refs/remotes/{REMOTE}/{branch}", capture=True)
    if result.returncode:
        raise RealignError(f"could not read {REMOTE}/{branch}")
    return result.stdout.strip()


def _contains(runner: Runner, root: Path, ancestor: str, descendant: str) -> bool:
    code = _git(runner, root, "merge-base", "--is-ancestor", ancestor, descendant).returncode
    if code not in (0, 1):
        raise RealignError(f"could not compare {ancestor} with {descendant}")
    return code == 0


def _push(runner: Runner, root: Path, commit: str) -> None:
    # A plain refspec: the remote refuses it unless it fast-forwards the branch.
    if _git(runner, root, "push", REMOTE, f"{commit}:refs/heads/{BRANCH}").returncode:
        raise RealignError(f"the push to {BRANCH} was refused; it moved or the credential cannot push to it")


def _merge(runner: Runner, root: Path, tip: str, production: str, name: str, email: str) -> None:
    if _git(runner, root, "checkout", "--quiet", "--detach", tip).returncode:
        raise RealignError(f"could not check out {BRANCH}")
    identity = ["-c", f"user.name={name}", "-c", f"user.email={email}", "-c", "commit.gpgsign=false"]
    if _git(runner, root, *identity, "merge", "--no-ff", "-m", MESSAGE, production).returncode:
        _git(runner, root, "merge", "--abort")
        raise RealignError(f"{PRODUCTION} conflicts with {BRANCH}; resolve it by merging {PRODUCTION} into {BRANCH} by hand. {BRANCH} is unchanged")
    head = _git(runner, root, "rev-parse", "HEAD", capture=True)
    if head.returncode:
        raise RealignError("could not read the merge commit")
    _push(runner, root, head.stdout.strip())


def realign(runner: Runner, root: Path, name: str, email: str) -> str:
    production = _fetch(runner, root, PRODUCTION)
    tip = _fetch(runner, root, BRANCH)
    if _contains(runner, root, production, tip):
        return f"{BRANCH} already contains {PRODUCTION}"
    if _contains(runner, root, tip, production):
        _push(runner, root, production)
        return f"fast-forwarded {BRANCH} to {PRODUCTION}"
    _merge(runner, root, tip, production, name, email)
    return f"merged {PRODUCTION} into {BRANCH}"


def main(argv: list[str] | None = None, runner: Runner = run, root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", required=True, help="author of the merge commit")
    parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    try:
        print(f"::notice::{realign(runner, root, args.name, args.email)}")
    except RealignError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
