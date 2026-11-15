"""A fingerprint per Molecule role: the content of everything its run reads.

The files are the role's watch set from `ci.scope.molecule_scope`, the same
set that decides whether a pull request queues the role, plus the paths every
scenario inherits. A role's fingerprint changes exactly when a pull request
touching those files would have queued it, so a measurement stays good for as
long as the fingerprint does.

The digest is taken over `git ls-files -s`, which lists each tracked file's
mode and blob id, so it follows content and not timestamps and needs no
history.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ci.proc import Runner, run
from ci.scope import molecule_scope as scope

# Pathspecs per `git ls-files` call, so a long watch set stays under the argument limit.
CHUNK = 200


class FingerprintError(Exception):
    """git could not list the files."""


def _listing(root: Path, paths: list[str], runner: Runner) -> list[str]:
    lines: list[str] = []
    for start in range(0, len(paths), CHUNK):
        result = runner(["git", "ls-files", "-s", "--", *paths[start : start + CHUNK]], root, True)
        if result.returncode != 0:
            raise FingerprintError(f"git ls-files exited {result.returncode} in {root}")
        lines += result.stdout.splitlines()
    return sorted(set(lines))


def fingerprints(root: Path, runner: Runner = run) -> dict[str, str]:
    """Role -> digest, for every role that has Molecule scenarios."""
    shared = [*scope.GLOBAL_PATHS, *scope.base_config_paths(root)]
    filters = scope.filter_index(root)
    utils = scope.module_utils_files(root)
    scan_cache: dict = {}
    import_cache: dict = {}
    out = {}
    for role in scope.role_names(root):
        watched = scope.watch_set(root, role, filters, scan_cache, utils, import_cache)
        listing = _listing(root, sorted({*watched, *shared}), runner)
        out[role] = hashlib.sha256("\n".join(listing).encode()).hexdigest()
    return out
