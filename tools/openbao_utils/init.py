#!/usr/bin/env python3
"""Initialise OpenBao on `security` over SSH (paramiko), so the operator
never types `docker exec` by hand.

It runs `docker exec` against the live `openbao` container, the one OpenBao
CLI path that cannot use the native `bao` client: the container crash-loops
until `step_ca_cert` issues its leaf cert, so there is no trustworthy network
path to it yet, and `docker exec` skips the network and TLS chain entirely
(ADR 0034).

`bao operator init` takes no input, so this runs a plain `docker exec` with
no PTY. Its output is the initial root token and the unseal key shares, which
belong only on the operator's screen and in their password manager
(docs/topics/secrets/openbao.md, First init). This script prints them and
nothing else: no logging, no file.

Usage:
    cd tools && python3 -m openbao_utils.init
"""

from __future__ import annotations

import sys

from utils.repo import OPENBAO_CONTAINER, TIMEOUT_SECONDS, connect_ssh, security_ssh_target


def main() -> int:
    client = connect_ssh(*security_ssh_target())
    try:
        command = f"docker exec {OPENBAO_CONTAINER} bao operator init -key-shares=3 -key-threshold=2"
        _stdin, stdout, stderr = client.exec_command(command, timeout=TIMEOUT_SECONDS)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        exit_status = stdout.channel.recv_exit_status()
    finally:
        client.close()

    sys.stdout.write(out)
    if err:
        sys.stderr.write(err)
    if exit_status != 0:
        print(f"\ninit failed (exit {exit_status}) - see output above.", file=sys.stderr)
        return 1

    print(
        "\nCopy the 3 unseal key shares and the root token above into the "
        "password manager entry now, plus one offline physical copy of one "
        "share - see docs/topics/secrets/openbao.md's First init section. Nothing above "
        "was written to disk or logged by this script."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
