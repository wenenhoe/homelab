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

Needs `gh` with GH_TOKEN set for attested entries, and `docker` for signed ones,
which runs `cosign` as the image COSIGN_IMAGE names. Standard library only.

Usage (from tools/): python -m ci.provenance.verify [IMAGE ...]
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ci import proc
from ci.images.remote import RemoteError, collect
from ci.output import write_summary
from ci.provenance.pins import Pin, pinned
from ci.provenance.registry import ENTRIES, Attested, Entry, Signed, validate
from ci.verification import ATTEMPTS, Sleep, attestation, verified

REPO_ROOT = Path(__file__).resolve().parents[3]
# Version 3 or later: version 2 finds no signature on some images that version 3 verifies.
COSIGN_IMAGE = "ghcr.io/sigstore/cosign/cosign:v3.1.4@sha256:0f06154836d2de34f887a5c273506d52ca43edaa1d9e53e6510fa78a48f69c2d"
# Where a committed key is mounted inside the container.
CONTAINER_KEY = "/key.pub"


@dataclass(frozen=True)
class Outcome:
    entry: Entry
    checked: int  # how many pinned digests the entry was run against
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _attested(entry: Attested, pin: Pin, root: Path, run: proc.Runner, sleep: Sleep, attempts: int) -> str | None:
    return attestation(f"oci://{pin.reference}", entry.repository, root, run, sleep, attempts, entry.source_ref)


def _cosign(root: Path, key: str | None) -> list[str]:
    """`docker run` for the cosign image, ready for its arguments.

    The image is distroless and runs as non-root, so the trust root it fetches
    is cached under /tmp, as cosign's own release pipeline does when it runs this
    image. It needs the network and nothing else: no capability, and only the one
    key file, read-only, when the entry has one.
    """
    argv = ["docker", "run", "--rm", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--env", "TUF_ROOT=/tmp"]
    if key:
        argv += ["--volume", f"{root / key}:{CONTAINER_KEY}:ro"]
    return [*argv, COSIGN_IMAGE]


def _signed(entry: Signed, pin: Pin, root: Path, run: proc.Runner, sleep: Sleep, attempts: int) -> str | None:
    base = [*_cosign(root, entry.key), "verify"]
    if entry.key:
        argv = [*base, "--key", CONTAINER_KEY, pin.reference]
    elif entry.identity:
        argv = [*base, "--certificate-identity", entry.identity, "--certificate-oidc-issuer", entry.issuer or "", pin.reference]
    else:
        argv = [*base, "--certificate-identity-regexp", entry.identity_regexp or "", "--certificate-oidc-issuer", entry.issuer or "", pin.reference]
    return verified("cosign verify", argv, root, run, sleep, attempts)


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
    write_summary("Image provenance", lines)
    return code


if __name__ == "__main__":
    sys.exit(main())
