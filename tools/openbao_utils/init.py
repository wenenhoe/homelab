#!/usr/bin/env python3
"""Initialise OpenBao on `security` over SSH (paramiko), so the operator
never types `docker exec` by hand.

It runs `docker exec` against the live `openbao` container, the one OpenBao
CLI path that cannot use the native `bao` client: the container crash-loops
until `step_ca_cert` issues its leaf cert, so there is no trustworthy network
path to it yet, and `docker exec` skips the network and TLS chain entirely
(ADR 0106).

`bao operator init` takes no input, so this runs a plain `docker exec` with
no PTY. Its output is the initial root token and the unseal key shares, which
belong only on the operator's screen and in their password manager
(docs/topics/secrets/openbao.md, First init). This script prints them and
nothing else: no logging, no file.

The output is shown as it arrives, and the wait for it is longer than the
connection timeout: the first init on an empty raft volume can sit silent for
longer than that, and a read that gave up early would lose the key shares of an
init that went on to succeed on the host. A silence that long is reported as
what it may be, not as a plain failure.

Usage:
    cd tools && python3 -m openbao_utils.init
"""

from __future__ import annotations

import sys

from utils.repo import OPENBAO_CONTAINER, connect_ssh, security_ssh_target

# Per read, not for the whole command.
INIT_TIMEOUT_SECONDS = 120

LOST_OUTPUT_DOC = "docs/topics/secrets/openbao-backup-restore.md, 'If init's output was lost'"


def main() -> int:
    client = connect_ssh(*security_ssh_target())
    try:
        command = f"docker exec {OPENBAO_CONTAINER} bao operator init -key-shares=3 -key-threshold=2"
        _stdin, stdout, stderr = client.exec_command(command, timeout=INIT_TIMEOUT_SECONDS)
        channel = stdout.channel
        try:
            while data := channel.recv(4096):
                sys.stdout.write(data.decode(errors="replace"))
                sys.stdout.flush()
        except TimeoutError:
            print(
                f"\nNo output from `bao operator init` for {INIT_TIMEOUT_SECONDS} s. It may still be running on "
                "security, or it may have finished with its output lost. Do not run it again yet: check "
                "`docker exec openbao bao status` on security. If that says Initialized true and no key shares "
                f"were shown above, they are lost; see {LOST_OUTPUT_DOC}.",
                file=sys.stderr,
            )
            return 1
        err = stderr.read().decode(errors="replace")
        exit_status = channel.recv_exit_status()
    finally:
        client.close()

    if err:
        sys.stderr.write(err)
    if exit_status != 0:
        print(f"\ninit failed (exit {exit_status}) - see output above.", file=sys.stderr)
        if "already initialized" in err:
            print(f"If you did not see its key shares, they are lost; see {LOST_OUTPUT_DOC}.", file=sys.stderr)
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
