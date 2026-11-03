#!/usr/bin/env python3
"""Remove a rebuilt host's old SSH host keys from known_hosts.

A rebuilt host has a new host key under the same name and address, so the first
SSH to it is refused until the old entries are gone. This removes the entries for
the host's short name, its fully qualified name and the address the lab's DNS
gives that name, then reads the file again and fails if any of them still
resolves to a key. `ssh-keygen -R` does the removal, so hashed entries go too and
the file is kept beside itself as `known_hosts.old`; the second read is what says
the entries are gone, whatever `ssh-keygen` reported.

Usage:
    cd tools && python3 -m rebuild_check.known_hosts <host> [--known-hosts PATH]

Exits 1 when an entry is still there or the host's name does not resolve.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import paramiko
from utils.repo import main_domain

DEFAULT_KNOWN_HOSTS = Path("~/.ssh/known_hosts")


def entries_for(host: str, resolve: Callable[[str], str] = socket.gethostbyname) -> list[str]:
    """The names a known_hosts line for the host can carry: short name, FQDN, address."""
    fqdn = f"{host}.internal.{main_domain()}"
    try:
        address = resolve(fqdn)
    except OSError as exc:
        raise SystemExit(f"{fqdn} does not resolve from here ({exc}): its address cannot be removed from known_hosts") from exc
    return [host, fqdn, address]


def remaining(known_hosts: Path, entries: list[str]) -> list[str]:
    """The entries that still resolve to a host key, hashed ones included."""
    keys = paramiko.HostKeys(str(known_hosts))
    return [entry for entry in entries if keys.lookup(entry) is not None]


def remove(known_hosts: Path, entries: list[str], run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> list[str]:
    """Run `ssh-keygen -R` for each entry, printing what it says, and return the entries still present."""
    for entry in entries:
        result = run(["ssh-keygen", "-R", entry, "-f", str(known_hosts)], capture_output=True, text=True, check=False)
        said = (result.stdout + result.stderr).strip()
        print(f"{entry}: {said or 'nothing said'}")
    return remaining(known_hosts, entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove a rebuilt host's old SSH host keys from known_hosts.")
    parser.add_argument("host")
    parser.add_argument("--known-hosts", type=Path, default=DEFAULT_KNOWN_HOSTS)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    known_hosts = args.known_hosts.expanduser()
    if not known_hosts.exists():
        print(f"{known_hosts} does not exist: nothing to remove")
        return 0
    left = remove(known_hosts, entries_for(args.host), run=subprocess.run)
    if left:
        print(f"\nstill in {known_hosts}: {', '.join(left)}", file=sys.stderr)
        return 1
    print(f"\nno entry for {args.host} remains in {known_hosts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
