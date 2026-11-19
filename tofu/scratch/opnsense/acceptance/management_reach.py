#!/usr/bin/env python3
"""Check from the Proxmox node which hosts on the scratch LAN reach the gateway's management ports.

    management_reach.py GATEWAY ALLOWED OTHER

ALLOWED is an address the seed admits (the node's own) and OTHER one it does not, both on the node's LAN
bridge. The admitted address must reach the GUI and API port (443), which proves the gateway answers and the
probe works; neither address may reach the SSH port (22, off in the seed); and the other address must not
reach 443. A blocked connection times out. Prints one line per check and exits 1 when any fails. Standard
library only, run on the node over ssh with the script on stdin: `python3 - GATEWAY ALLOWED OTHER < file`.
"""

from __future__ import annotations

import socket
import sys
from collections.abc import Callable

TIMEOUT = 3.0
GUI_PORT = 443
SSH_PORT = 22


def connects(gateway: str, port: int, source: str) -> bool:
    try:
        with socket.create_connection((gateway, port), timeout=TIMEOUT, source_address=(source, 0)):
            return True
    except OSError:
        return False


def run(gateway: str, allowed: str, other: str, connect: Callable[[str, int, str], bool] = connects) -> int:
    expectations = [
        (allowed, GUI_PORT, True, "the admitted address reaches the GUI and API port"),
        (allowed, SSH_PORT, False, "the admitted address does not reach the SSH port"),
        (other, GUI_PORT, False, "another address on the LAN does not reach the GUI and API port"),
        (other, SSH_PORT, False, "another address on the LAN does not reach the SSH port"),
    ]
    failed = 0
    for source, port, expected, label in expectations:
        reached = connect(gateway, port, source)
        ok = reached == expected
        failed += not ok
        print(f"REACH {label}: {'PASS' if ok else 'FAIL'} (from {source} to {gateway}:{port}, connected={reached})", flush=True)
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or len({*argv}) != 3:
        print("usage: management_reach.py GATEWAY ALLOWED OTHER (three different addresses)", file=sys.stderr)
        return 2
    return run(*argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
