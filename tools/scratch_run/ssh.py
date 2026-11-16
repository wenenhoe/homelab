"""The ssh master connection a run rides on.

`scratch_gateway.sh` and the node backend talk to the node with `BatchMode`, so neither can answer a prompt: a master
connection has to be open first, at the socket named by `SSH_CONTROL_PATH`, and every ssh command then multiplexes
over it, including the gateway's GUI tunnel (`-O forward`). `Master` checks that socket, opens the master when it is
down (this is where a key passphrase, a password or a hardware-key touch is asked for, on your terminal) and closes it.
An opened master stays up for an hour after its last use, so repeated runs ask once.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from scratch_run.gateway_steps import Runner, run_command

DEFAULT_SOCKET = Path("~/.cache/scratch-run/ssh.sock")
PERSIST = "1h"
CHECK_TIMEOUT = 30


def run_interactive(argv: Sequence[str]) -> int:
    """Run a command on this terminal, so ssh can ask its questions."""
    try:
        return subprocess.run(list(argv), check=False).returncode
    except FileNotFoundError:
        return 127


class Master:
    def __init__(self, node: str, socket: Path, run: Runner = run_command, interactive: Callable[[Sequence[str]], int] = run_interactive) -> None:
        self.node = node
        self.socket = socket.expanduser()
        self.run = run
        self.interactive = interactive

    def _ssh(self, *options: str) -> list[str]:
        return ["ssh", "-o", f"ControlPath={self.socket}", *options]

    def is_up(self) -> bool:
        return self.run(self._ssh("-O", "check", self.node), timeout=CHECK_TIMEOUT)[0] == 0

    def ensure(self) -> str | None:
        """Open the master unless it is up; None on success, else what went wrong."""
        if self.is_up():
            return None
        self.socket.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.socket.is_socket():  # a master that died leaves its socket, and a new master refuses to start beside it
            self.socket.unlink()
        argv = self._ssh("-M", "-N", "-f", "-o", f"ControlPersist={PERSIST}", "-o", "ServerAliveInterval=15", "-o", "ConnectTimeout=15", self.node)
        status = self.interactive(argv)
        if status != 0:
            return f"ssh to {self.node} failed (exit {status}); try `ssh {self.node}` by hand"
        if not self.is_up():
            return f"ssh to {self.node} connected, but no master is listening at {self.socket}"
        return None

    def close(self) -> bool:
        """Close the master; True when one was open."""
        return self.run(self._ssh("-O", "exit", self.node), timeout=CHECK_TIMEOUT)[0] == 0
