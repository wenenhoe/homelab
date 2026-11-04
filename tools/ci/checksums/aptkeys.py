#!/usr/bin/env python3
"""Does each vendor still serve the apt signing key the repository pins?

The docker and tailscale_node roles install a vendor's apt key only when it
holds exactly one primary key with the fingerprint pinned in the role's
defaults (docs/topics/deploy/apt-signing-keys.md). That stops a bad key on a
host, at the run that downloads it. This asks each vendor the same question
ahead of time: it downloads the key from the address the role uses and
requires the same result, so a rotation shows up in a weekly run or in the
pull request that changes a pin, not on the next deploy.

A failure of any key fails the run, an unreachable one included: a pin that
could not be compared has not been shown to match.

Needs `gpg`. Standard library only.

Usage (from tools/): python -m ci.checksums.aptkeys [KEY ...]
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ci import proc
from ci.checksums import pins
from ci.checksums.registry import Location
from ci.checksums.verify import REPO_ROOT, FetchError, Http
from ci.output import write_summary

FINGERPRINT = re.compile(r"[0-9A-F]{40}")
_FINGERPRINT_FIELD = 9


@dataclass(frozen=True)
class AptKey:
    name: str
    # The address the role downloads the key from.
    url: str
    # The role default that pins the key's fingerprint.
    pin: Location


# Tailscale serves one key file for each Ubuntu release. The roles ask for the
# release the host runs, which is 26.04 (resolute) on every host that has the
# role today.
KEYS = (
    AptKey("docker", "https://download.docker.com/linux/ubuntu/gpg", Location("ansible/roles/docker/defaults/main.yaml", "docker_apt_key_fingerprint")),
    AptKey(
        "tailscale",
        "https://pkgs.tailscale.com/stable/ubuntu/resolute.noarmor.gpg",
        Location("ansible/roles/tailscale_node/defaults/main.yaml", "tailscale_node_apt_key_fingerprint"),
    ),
)


def primary_fingerprints(colons: str) -> list[str]:
    """The fingerprint of each primary public key in `gpg --with-colons` output, in order.

    The same rule as ansible/filter_plugins/gpg_keys.py, which the roles use:
    a subkey's `fpr` record and a secret key's are not a primary public key's.
    """
    found: list[str] = []
    after_primary = False
    for line in colons.splitlines():
        record = line.split(":")
        if record[0] == "pub":
            after_primary = True
        elif record[0] == "fpr" and after_primary:
            if len(record) <= _FINGERPRINT_FIELD or not record[_FINGERPRINT_FIELD]:
                raise ValueError(f"an fpr record has no fingerprint: {line}")
            found.append(record[_FINGERPRINT_FIELD])
            after_primary = False
        elif record[0] in {"sub", "sec", "ssb"}:
            after_primary = False
    return found


@dataclass(frozen=True)
class Outcome:
    key: AptKey
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def check_key(root: Path, key: AptKey, fetch: Callable[[str], bytes], run: proc.Runner = proc.run) -> Outcome:
    try:
        pinned = pins.read_value(root, key.pin)
        if not FINGERPRINT.fullmatch(pinned):
            return Outcome(key, [f"{key.pin.name} isn't a 40-character upper-case fingerprint"])
        body = fetch(key.url)
    except (pins.PinError, FetchError) as exc:
        return Outcome(key, [str(exc)])
    # gpg stops when its home is missing, so it gets a throwaway one.
    home = Path(tempfile.mkdtemp(prefix="aptkey-"))
    try:
        file = home / "key"
        file.write_bytes(body)
        try:
            result = run(["gpg", "--no-options", "--homedir", str(home), "--batch", "--no-tty", "--show-keys", "--with-colons", str(file)], home, True)
        except FileNotFoundError:
            return Outcome(key, ["gpg is not installed"])
        if result.returncode != 0:
            return Outcome(key, [f"gpg can't read the key downloaded from {key.url}"])
        try:
            held = primary_fingerprints(result.stdout)
        except ValueError as exc:
            return Outcome(key, [str(exc)])
    finally:
        shutil.rmtree(home, ignore_errors=True)
    if held != [pinned]:
        return Outcome(key, [f"{key.url} holds {', '.join(held) or 'no primary key'}, not only the pinned {pinned}"])
    return Outcome(key, [])


def report(outcomes: list[Outcome]) -> tuple[list[str], int]:
    """(lines to print, exit code)."""
    lines = [f"::error::{o.key.name} ({o.key.pin.path}): {error}" for o in outcomes for error in o.errors]
    failed = [o for o in outcomes if not o.ok]
    lines.append(
        f"{len(outcomes)} apt keys: {len(outcomes) - len(failed)} passed, {len(failed)} failed ("
        + ", ".join(f"{o.key.name}{'' if o.ok else ' FAILED'}" for o in outcomes)
        + ")"
    )
    return lines, 1 if failed else 0


def main(
    argv: list[str] | None = None,
    root: Path = REPO_ROOT,
    keys: tuple[AptKey, ...] = KEYS,
    http: Http | None = None,
    run: proc.Runner = proc.run,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("names", nargs="*", metavar="KEY", help="check only these keys")
    args = parser.parse_args(argv)
    unknown = sorted(set(args.names) - {key.name for key in keys})
    if unknown:
        parser.error(f"no apt key named {', '.join(unknown)}")
    client = http or Http()
    outcomes = [check_key(root, key, client.fetch, run) for key in keys if not args.names or key.name in args.names]
    lines, code = report(outcomes)
    print("\n".join(lines))
    write_summary("Apt signing keys", lines)
    return code


if __name__ == "__main__":
    sys.exit(main())
