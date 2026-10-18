#!/usr/bin/env python3
"""Clone each pinned Bats repository by commit SHA, and refuse any clone that is not at the pin.

Each pin in `pins.txt` is fetched into DIR/<repository name> by its SHA, not by
its tag, and the clone's HEAD must equal the SHA. A directory that is already
there is not touched: it is accepted when its HEAD is the pin and refused
otherwise, so a stale clone is never run in place of the pinned one. A fetch
that fails leaves no directory behind.

Needs `git` and, for the default remote, GitHub. Standard library only.

Usage (from tools/): python3 -m ci.shell_tests.fetch DIR
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from ci import proc
from ci.shell_tests.pins import GITHUB, PIN_FILE, Pin, PinError, load


def head(clone: Path, run: proc.Runner) -> str | None:
    """The commit `clone` has checked out, or None when it is not a repository with one.

    The git directory is named so that a directory inside another repository
    is not read as that repository.
    """
    done = run(["git", f"--git-dir={clone / '.git'}", "rev-parse", "--verify", "--quiet", "HEAD"], clone, True)
    return done.stdout.strip() if done.returncode == 0 else None


def _clone(pin: Pin, clone: Path, base: str, run: proc.Runner) -> str | None:
    """None once `clone` holds the pinned commit, else why it doesn't."""
    steps = [
        ("init", ["git", "-c", "advice.defaultBranchName=false", "init", "--quiet"]),
        ("fetch", ["git", "fetch", "--quiet", "--depth", "1", "--no-tags", pin.url(base), pin.sha]),
        ("checkout", ["git", "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", "FETCH_HEAD"]),
    ]
    for name, argv in steps:
        if run(argv, clone, False).returncode != 0:
            return f"git {name} failed"
    return None


def fetch(pins: list[Pin], dest: Path, base: str = GITHUB, run: proc.Runner = proc.run) -> list[str]:
    """One message per pin that is not now at its SHA under `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    errors = []
    for pin in pins:
        clone = dest / pin.name
        if clone.exists():
            found = head(clone, run)
            if found != pin.sha:
                errors.append(f"{clone} is at {found or 'no commit'}, not the pinned {pin.sha} for {pin.repository} {pin.tag}; remove it to fetch the pin")
            continue
        clone.mkdir()
        try:
            problem = _clone(pin, clone, base, run)
        except FileNotFoundError:
            shutil.rmtree(clone)
            return ["git is not installed"]
        found = head(clone, run) if problem is None else None
        if problem is None and found != pin.sha:
            problem = f"HEAD is {found or 'no commit'}, not the pinned {pin.sha}"
        if problem:
            shutil.rmtree(clone)
            errors.append(f"{pin.repository} {pin.tag}: {problem}")
    return errors


def main(argv: list[str] | None = None, base: str = GITHUB, run: proc.Runner = proc.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dir", type=Path, help="the directory to clone into, one subdirectory per pin")
    parser.add_argument("--pinfile", type=Path, default=PIN_FILE)
    args = parser.parse_args(argv)
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")
    try:
        pins = load(args.pinfile)
    except PinError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    errors = fetch(pins, args.dir, base, run)
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print("\n".join(f"{pin.name} {pin.tag} {pin.sha}" for pin in pins))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
