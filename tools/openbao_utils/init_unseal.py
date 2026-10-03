#!/usr/bin/env python3
"""Init/unseal orchestration for OpenBao on `security`, over paramiko
rather than a human SSHing in directly to run docker exec by hand.

The remote command stays docker-exec-against-the-live-container for
both subcommands, permanently - the one place this repo's OpenBao CLI
surface keeps that pattern by necessity, not convention:
compose.yaml.j2 publishes OpenBao's port directly, but the container
crash-loops until step_ca_cert issues its leaf cert, so there's no
trustworthy network path to it during that window - docker exec
bypasses the network/TLS chain entirely, which is why it's the one
thing that works here. See ADR 0034's Context/Decision for the full
reasoning.

`init` needs no PTY: it takes no interactive input and prints its
output (three unseal key shares, the initial root token) directly -
confirmed against the real CLI's own usage text (bao operator init -h),
which shows no prompt of any kind. Its remote command is plain
`docker exec <container> ...`, no `-i`/`-t` - the same non-interactive
shape utils.repo.fetch_root_cert already uses successfully for a
different docker exec call, not a new untested pattern.

`unseal` does need one: bao operator unseal's own masked-input prompt
refuses a bare, non-PTY pipe outright ("file descriptor 0 is not a
terminal", confirmed live during ADR 0034's own de-risking spike), so
its channel is opened with get_pty=True and its remote command keeps
the
`-it` a human would type by hand (`docker exec -t` needs to allocate a
pty *inside the container* for bao's own isatty() check to pass -
independent of, but only reachable because of, the pty already present
on the outer SSH channel). This exact shape - get_pty=True driving
`docker exec -it ... bao operator unseal` - is what that spike already
confirmed live, unsealing a real 3-share/2-threshold throwaway
instance this way; this module is a mechanical translation of that
result into something reusable, not new de-risking. A share is only
ever written to the channel's own stdin after being read locally via
getpass - never as a positional argument, so it never touches this
process's argv or appears in `ps` on either end.

Both subcommands print the remote output directly to this process's own
stdout as it arrives - nothing here captures, logs, or stores it
anywhere, for the same reason docs/topics/secrets/openbao.md's own runbook has never
been an Ansible task: init's output includes the initial root token and
raw unseal key shares, and the only safe place for that to land is the
operator's own eyes and the password manager entry they copy it into by
hand.

`unseal`'s own exit status is checked, not printed-and-ignored: confirmed
live (a real 3-share/2-threshold instance) that submitting one share of
two - still sealed afterward, `Unseal Progress 1/2` - exits 0, same as
a share that completes the unseal. `bao operator unseal` evidently
doesn't follow `bao status`'s own sealed=2 convention at all; its exit
code tracks whether the command itself ran, not the resulting seal
state. A nonzero exit here is therefore a genuine failure (bad share,
connection lost, container not running), not partial progress, and
`unseal` fails loudly on one - see the module for the exact live
transcript this rests on if it's ever worth re-checking against a
different OpenBao version.

Usage:
    cd tools && python3 -m openbao_utils.init_unseal init
    cd tools && python3 -m openbao_utils.init_unseal unseal
"""

from __future__ import annotations

import getpass
import sys
import time

import paramiko
from utils.repo import TIMEOUT_SECONDS, security_ssh_target

OPENBAO_CONTAINER = "openbao"

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


def _connect() -> paramiko.SSHClient:
    user, host, key_path = security_ssh_target()
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    # Same accept-new-equivalent policy as utils.repo.fetch_root_cert -
    # see docs/decisions/0030-openbao-client-implementation-in-repo-python/revision-000.md.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, key_filename=key_path, timeout=TIMEOUT_SECONDS)
    return client


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


def run_init() -> int:
    client = _connect()
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


def run_unseal_share() -> int:
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

    client = _connect()
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

    # Not a partial-progress false alarm: confirmed live that a share
    # accepted but not yet meeting the threshold ("Unseal Progress 1/2",
    # still sealed) exits 0, same as a share that completes the unseal -
    # see the module docstring. A nonzero exit here is a real failure.
    if exit_status != 0:
        print(f"\nunseal failed (exit {exit_status}) - see output above.", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("init", "unseal"):
        print(f"Usage: {sys.argv[0]} init|unseal", file=sys.stderr)
        return 1
    return run_init() if sys.argv[1] == "init" else run_unseal_share()


if __name__ == "__main__":
    raise SystemExit(main())
