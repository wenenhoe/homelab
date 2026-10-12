#!/usr/bin/env python3
"""Unseal OpenBao on `security` over SSH (paramiko), one key share per run,
so the operator never types `docker exec` by hand.

It runs `docker exec` against the live `openbao` container, the one OpenBao
CLI path that cannot use the native `bao` client: the container crash-loops
until `step_ca_cert` issues its leaf cert, so there is no trustworthy network
path to it yet, and `docker exec` skips the network and TLS chain entirely
(ADR 0034).

`bao operator unseal` needs a PTY: its masked key prompt refuses a
non-terminal stdin. The channel is opened with `get_pty=True` and the command
keeps `-it`, since `-t` makes docker allocate the second pty inside the
container that bao's own `isatty()` check needs. The share is read locally
with `getpass` and written only to the channel's stdin, never as an argument,
so it is not in argv or `ps` on either end. Remote output goes straight to
this process's stdout; nothing is captured, logged or stored.

`bao operator unseal` exits 0 even when a share leaves OpenBao still sealed
(`Unseal Progress 1/2`), so its exit status tracks whether the command ran,
not the seal state. A nonzero exit is a real failure (bad share, lost
connection, container not running), and this fails on it. Run it once per
share until the threshold is met.

Usage:
    cd tools && python3 -m openbao_utils.unseal
"""

from __future__ import annotations

import getpass
import sys
import time

import paramiko
from utils.repo import OPENBAO_CONTAINER, TIMEOUT_SECONDS, connect_ssh, security_ssh_target

# bao's own prompt text, as it prints it. The share is already read locally
# by then, so showing it would look like a second prompt that never waits.
_REMOTE_PROMPT = "Unseal Key (will be hidden):"

# How long _drain() waits for the first output before giving up - generous,
# since docker exec and bao's own startup can lag. Reusing TIMEOUT_SECONDS
# (utils.repo's one shared bound for a single SSH operation) rather than a
# second constant. Never bounds the human's own time spent typing a share:
# that happens locally, before the channel is opened.
_DRAIN_IDLE_SECONDS = TIMEOUT_SECONDS

# Quiet time after output that ends a drain. Short on purpose: it is the
# delay between bao's prompt appearing and the share being sent.
_DRAIN_SETTLE_SECONDS = 0.5


def _drain(channel: paramiko.Channel, *, echo: bool = True) -> str:
    """Collects whatever's currently available on the channel and, unless
    echo is False, prints it to this process's own stdout live - the
    human should see the remote output exactly as if they'd typed the
    command themselves. Waits up to _DRAIN_IDLE_SECONDS for the first
    output, then returns once _DRAIN_SETTLE_SECONDS passes with nothing
    new arriving, or as soon as the remote command has exited. The PTY
    already handles the actual masking. Returns the text it collected."""
    collected = ""
    deadline = time.monotonic() + _DRAIN_IDLE_SECONDS
    while time.monotonic() < deadline:
        if channel.recv_ready():
            data = channel.recv(4096)
            if not data:
                return collected
            text = data.decode(errors="replace")
            collected += text
            if echo:
                sys.stdout.write(text)
                sys.stdout.flush()
            deadline = time.monotonic() + _DRAIN_SETTLE_SECONDS
        elif channel.exit_status_ready():
            return collected
        else:
            time.sleep(0.05)
    return collected


def main() -> int:
    """Drives exactly one share through the real masked prompt over a
    get_pty=True channel - bao operator unseal only ever asks for one
    share per invocation. Run this twice for a 2-of-3 threshold."""
    # Read before the channel opens: getpass's terminal-mode change
    # discards anything already typed, so a share pasted as soon as the
    # remote prompt shows would be echoed in clear and lost, and bao would
    # receive an empty key.
    share = getpass.getpass("Unseal key share (hidden): ")
    if not share:
        print("No key share entered - nothing sent.", file=sys.stderr)
        return 1

    client = connect_ssh(*security_ssh_target())
    try:
        stdin, stdout, _stderr = client.exec_command(
            f"docker exec -it {OPENBAO_CONTAINER} bao operator unseal",
            get_pty=True,
            timeout=TIMEOUT_SECONDS,
        )
        channel = stdout.channel

        # Anything other than bao's prompt (a docker error, say) is still shown.
        before_share = _drain(channel, echo=False).replace(_REMOTE_PROMPT, "").strip()
        if before_share:
            sys.stdout.write(before_share + "\n")
        stdin.write(share + "\n")
        stdin.flush()

        _drain(channel)
        while not channel.exit_status_ready():
            time.sleep(0.1)
            _drain(channel)
        exit_status = channel.recv_exit_status()
    finally:
        client.close()

    # A share short of the threshold exits 0 too (see the module docstring),
    # so a nonzero exit is a real failure, not partial progress.
    if exit_status != 0:
        print(f"\nunseal failed (exit {exit_status}) - see output above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
