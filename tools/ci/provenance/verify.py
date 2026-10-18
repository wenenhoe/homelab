#!/usr/bin/env python3
"""Is each pinned image digest the one its publisher signed or attested?

Every digest the tree pins (ci.provenance.pins) for an image repository in the
registry (ci.provenance.registry) is verified by the repository's tier: `gh
attestation verify` for the repository an attested entry names, `cosign verify`
with the identity and issuer a signed entry fixes or with its committed public
key, and nothing for an unsigned entry. The repository, the identity and the
key come from the entry, never from the registry or the image being checked. A
host still pulls the pinned digest; this shows the digest was not copied from
an image its publisher never built.

A failure of any digest fails the run, an unreachable registry or API included:
the tools' exit status does not tell a missing statement from a call that got
no answer, and a digest that could not be verified has not been shown to be the
publisher's. Each tool call is made up to three times, so a passing blip does
not fail a run, and a failing statement fails all three.

Needs `gh` with GH_TOKEN set for attested entries, and `cosign` for signed ones.
Standard library only.

Usage (from tools/): python -m ci.provenance.verify [IMAGE ...]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ci import proc
from ci.images.remote import RemoteError, collect
from ci.provenance.pins import Pin, pinned
from ci.provenance.registry import ENTRIES, Attested, Entry, Signed, validate

REPO_ROOT = Path(__file__).resolve().parents[3]
ATTEMPTS = 3
Sleep = Callable[[float], None]


@dataclass(frozen=True)
class Outcome:
    entry: Entry
    checked: int  # how many pinned digests the entry was run against
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _verified(command: str, argv: list[str], root: Path, run: proc.Runner, sleep: Sleep, attempts: int) -> str | None:
    """None when the tool exits 0 within its attempts, else why not."""
    code = 0
    for attempt in range(attempts):
        if attempt:
            sleep(2.0**attempt)
        try:
            # Both tools print what they verified; the exit code is the whole answer.
            done = run(argv, root, True)
        except FileNotFoundError:
            return f"{argv[0]} is not installed"
        if done.returncode == 0:
            return None
        code = done.returncode
    return f"{command} exited {code} after {attempts} attempts"


def _attested(entry: Attested, pin: Pin, root: Path, run: proc.Runner, sleep: Sleep, attempts: int) -> str | None:
    argv = ["gh", "attestation", "verify", f"oci://{pin.reference}", "--repo", entry.repository]
    return _verified("gh attestation verify", argv, root, run, sleep, attempts)


def _signed(entry: Signed, pin: Pin, root: Path, run: proc.Runner, sleep: Sleep, attempts: int) -> str | None:
    if entry.key:
        argv = ["cosign", "verify", "--key", str(root / entry.key), pin.reference]
    elif entry.identity:
        argv = ["cosign", "verify", "--certificate-identity", entry.identity, "--certificate-oidc-issuer", entry.issuer or "", pin.reference]
    else:
        argv = [
            "cosign",
            "verify",
            "--certificate-identity-regexp",
            entry.identity_regexp or "",
            "--certificate-oidc-issuer",
            entry.issuer or "",
            pin.reference,
        ]
    return _verified("cosign verify", argv, root, run, sleep, attempts)


def check_entry(root: Path, entry: Entry, pins: list[Pin], run: proc.Runner, sleep: Sleep = time.sleep, attempts: int = ATTEMPTS) -> Outcome:
    """Run an entry's tier against every digest the tree pins for its repository."""
    mine = [pin for pin in pins if pin.registry_key == entry.registry_key]
    if isinstance(entry, Signed) and entry.key and mine and not (root / entry.key).is_file():
        return Outcome(entry, len(mine), [f"the key file {Path(entry.key).name} is not committed"])
    errors = []
    for pin in mine:
        if isinstance(entry, Attested):
            problem = _attested(entry, pin, root, run, sleep, attempts)
        elif isinstance(entry, Signed):
            problem = _signed(entry, pin, root, run, sleep, attempts)
        else:
            problem = None
        if problem:
            errors.append(f"{pin.reference} ({', '.join(pin.sources)}): {problem}")
    return Outcome(entry, len(mine), errors)


def report(outcomes: list[Outcome], problems: list[str]) -> tuple[list[str], int]:
    """(lines to print, exit code)."""
    lines = [f"::error::{problem}" for problem in problems]
    for outcome in outcomes:
        if not outcome.checked:
            lines.append(f"::notice::{outcome.entry.image}: no digest of it is pinned in the tree, so there is nothing to verify")
        lines.extend(f"::error::{outcome.entry.image}: {error}" for error in outcome.errors)
    failed = [outcome for outcome in outcomes if not outcome.ok]
    lines.append(
        f"{len(outcomes)} images: {len(outcomes) - len(failed)} passed, {len(failed)} failed ("
        + ", ".join(f"{outcome.entry.image} [{outcome.entry.tier.value}]{'' if outcome.ok else ' FAILED'}" for outcome in outcomes)
        + ")"
    )
    return lines, 1 if failed or problems else 0


def main(
    argv: list[str] | None = None,
    root: Path = REPO_ROOT,
    entries: tuple[Entry, ...] = ENTRIES,
    run: proc.Runner = proc.run,
    sleep: Sleep = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("images", nargs="*", metavar="IMAGE", help="check only these registry entries, named as the registry writes them")
    args = parser.parse_args(argv)
    try:
        validate(entries)
    except ValueError as exc:
        parser.error(str(exc))
    unknown = sorted(set(args.images) - {entry.image for entry in entries})
    if unknown:
        parser.error(f"no registry entry named {', '.join(unknown)}")
    try:
        collected = collect(root)
    except RemoteError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    pins, problems = pinned(collected)
    outcomes = [check_entry(root, entry, pins, run, sleep) for entry in entries if not args.images or entry.image in args.images]
    lines, code = report(outcomes, [*collected.problems, *problems])
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write("### Image provenance\n\n" + "\n".join(f"- {line}" for line in lines) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
