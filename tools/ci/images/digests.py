#!/usr/bin/env python3
"""Does every image reference the repo names carry a digest?

A deploy runs the image a commit names only if the commit names it by digest
(ADR 0083). This collects every reference the weekly tag check collects
(ci.images.remote: compose files, Ansible YAML, Dockerfiles, and the pins
Renovate's regex managers track) and fails on:

- a reference with no `@sha256:` digest that is not listed in FLOATING;
- a FLOATING entry nothing names any more, or one that is pinned after all;
- one `name:tag` pinned to two different digests in different files, which
  Renovate's groups are there to prevent: a tag has one digest at a time.

A reference that cannot be pinned (a template, `scratch`, a `:local` build)
is skipped by the collection and is not judged here.

Usage (from tools/): python -m ci.images.digests check
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ci.images import remote

REPO_ROOT = Path(__file__).resolve().parents[3]

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

# Each reference that stays on a floating tag, and why. Test platforms only:
# nothing here is deployed to a host.
FLOATING: dict[str, str] = {
    "geerlingguy/docker-ubuntu2604-ansible:latest": (
        "Molecule's systemd-in-Docker Ubuntu 26.04 platform, followed on purpose so the scenarios run on the current base; it only boots, no host runs it"
    ),
    "hello-world": "the docker role's Molecule scenario runs it once to prove the daemon can pull and run a container",
}


def check(root: Path, floating: dict[str, str] = FLOATING) -> list[str]:
    """Every disagreement between the references the repo names and the rule above."""
    collected = remote.collect(root)
    errors = [f"Renovate: {problem}" for problem in collected.problems]
    by_name: dict[str, set[str]] = {}
    unpinned: dict[str, list[str]] = {}
    for text, files in collected.images.items():
        name, _, digest = text.partition("@")
        if not digest:
            unpinned[name] = files
        elif not _DIGEST.match(digest):
            errors.append(f"{text} ({', '.join(files)}): {digest!r} is not a sha256 digest")
        else:
            by_name.setdefault(name, set()).add(digest)
    for name, digests in sorted(by_name.items()):
        if len(digests) > 1:
            errors.append(f"{name} is pinned to {len(digests)} different digests ({', '.join(sorted(digests))}); one tag has one digest, so move them together")
    for name, files in sorted(unpinned.items()):
        if name not in floating:
            errors.append(f"{name} ({', '.join(files)}): has no @sha256 digest; pin it, or list it in ci.images.digests.FLOATING with a reason")
    for name in sorted(floating):
        if name not in unpinned:
            errors.append(f"{name} is listed in ci.images.digests.FLOATING but is {'pinned' if name in by_name else 'not named anywhere'}; remove the entry")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_subparsers(dest="command", required=True).add_parser("check")
    parser.parse_args(argv)
    try:
        errors = check(REPO_ROOT)
    except remote.RemoteError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print("Every image reference carries a digest or is listed as floating.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
