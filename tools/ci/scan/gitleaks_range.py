#!/usr/bin/env python3
"""Runs gitleaks over the commits of a pull request.

The pre-commit gitleaks hook scans only what is staged, so under `--all-files`
in CI it finds nothing. This runs the same gitleaks build, the one pre-commit
already compiled for the rev pinned in the pre-commit config, over
`<base>..<head>`, so a secret committed anywhere in the PR fails the job even
if a later commit removed it. The binary is looked up in pre-commit's own
cache rather than pinned a second time; the hook environments must already be
installed.

Usage: python3 -m ci.scan.gitleaks_range <base-sha> <head-sha>
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

from ci.proc import Runner, run

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG = ".config/.pre-commit-config.yaml"
GITLEAKS_REPO = "https://github.com/gitleaks/gitleaks"
# pre-commit names the environment after the Go it uses: "system" when the runner has Go on PATH, "default" when it downloads one.
BINARY_GLOB = "golangenv-*/bin/gitleaks"
REV = re.compile(rf"repo:\s*{re.escape(GITLEAKS_REPO)}\s*\n\s*rev:\s*(\S+)")


class GitleaksUnavailableError(Exception):
    """The pinned gitleaks build can't be found, so nothing can be scanned."""


def pinned_rev(config_text: str) -> str:
    match = REV.search(config_text)
    if not match:
        raise GitleaksUnavailableError(f"{CONFIG} pins no {GITLEAKS_REPO} rev")
    return match.group(1)


def cache_dir(environ: dict[str, str]) -> Path:
    if "PRE_COMMIT_HOME" in environ:
        return Path(environ["PRE_COMMIT_HOME"])
    base = Path(environ["XDG_CACHE_HOME"]) if "XDG_CACHE_HOME" in environ else Path(environ.get("HOME", "~")).expanduser() / ".cache"
    return base / "pre-commit"


def binary(cache: Path, rev: str) -> Path:
    db = cache / "db.db"
    if not db.is_file():
        raise GitleaksUnavailableError(f"no pre-commit cache at {db}; install the hook environments first")
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT path FROM repos WHERE repo = ? AND ref = ?", (GITLEAKS_REPO, rev)).fetchone()
    if not row:
        raise GitleaksUnavailableError(f"gitleaks {rev} is not in the pre-commit cache; install the hook environments first")
    found = sorted(path for path in Path(row[0]).glob(BINARY_GLOB) if path.is_file())
    if not found:
        raise GitleaksUnavailableError(f"no gitleaks binary under {row[0]}/{BINARY_GLOB}")
    return found[0]


def command(path: Path, base: str, head: str) -> list[str]:
    return [str(path), "git", "--redact", "--verbose", "--no-banner", f"--log-opts={base}..{head}", "."]


def main(argv: list[str] | None = None, runner: Runner = run, root: Path = REPO_ROOT, environ: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("base")
    parser.add_argument("head")
    args = parser.parse_args(argv)
    try:
        rev = pinned_rev((root / CONFIG).read_text())
        path = binary(cache_dir(dict(os.environ) if environ is None else environ), rev)
    except GitleaksUnavailableError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return runner(command(path, args.base, args.head), root, False).returncode


if __name__ == "__main__":
    sys.exit(main())
