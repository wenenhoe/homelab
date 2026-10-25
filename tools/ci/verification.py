"""Calling `gh` and `cosign` for the CI checks that verify a pinned artifact, and the retry schedule those checks share.

Neither tool's exit status separates a missing statement from a registry or API
that did not answer, so a call is made up to ATTEMPTS times, pausing longer
between attempts: a failure that passes on a second try does not fail a run, and
a statement that is missing fails every attempt. A tool that is not installed
fails at once.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from ci import proc

ATTEMPTS = 3
Sleep = Callable[[float], None]


def backoff(attempt: int) -> float:
    """Seconds to wait before attempt number `attempt`, counting from 0, which does not wait."""
    return 2.0**attempt


def verified(command: str, argv: list[str], cwd: Path, run: proc.Runner, sleep: Sleep = time.sleep, attempts: int = ATTEMPTS) -> str | None:
    """None when the tool exits 0 within its attempts, else why not."""
    code = 0
    for attempt in range(attempts):
        if attempt:
            sleep(backoff(attempt))
        try:
            # `gh` prints nothing on success when it is not attached to a terminal and `cosign` prints what it verified; the exit code is the whole answer.
            done = run(argv, cwd, True)
        except FileNotFoundError:
            return f"{argv[0]} is not installed"
        if done.returncode == 0:
            return None
        code = done.returncode
    return f"{command} exited {code} after {attempts} attempts"


def attestation(
    subject: str, repository: str, cwd: Path, run: proc.Runner, sleep: Sleep = time.sleep, attempts: int = ATTEMPTS, source_ref: str | None = None
) -> str | None:
    """None when `gh attestation verify` accepts `subject` as built by `repository`, else why not. A subject is a file path or `oci://` reference.

    With `source_ref`, the attestation must also name that git ref as the one the build ran from.
    """
    argv = ["gh", "attestation", "verify", subject, "--repo", repository]
    if source_ref:
        argv += ["--source-ref", source_ref]
    return verified("gh attestation verify", argv, cwd, run, sleep, attempts)
