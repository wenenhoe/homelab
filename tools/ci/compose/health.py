#!/usr/bin/env python3
"""Waits for every service in a running compose stack to be healthy.

For each service: if its container defines a healthcheck, poll until it
reports healthy (failing at once on unhealthy, or when it never gets there
within `tries` polls); if it doesn't, wait out a grace period and confirm the
container is still running, which still catches an immediate crash-loop or
a bad entrypoint. A service with no container fails as never started, and a
service with several containers is checked container by container. On any
failure the container's logs are printed.

Used by _compose-boot-test.yml (compose-boot-test and compose-boot-test-all
both call that one reusable workflow).

Usage (from tools/): python -m ci.compose.health <path-to-compose.yaml>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from ci.proc import Runner, run

REPO_ROOT = Path(__file__).resolve().parents[3]

POLL_TRIES = 30
POLL_INTERVAL = 2.0
NO_HEALTHCHECK_GRACE = 10.0


def _output(runner: Runner, args: list[str]) -> tuple[int, str]:
    result = runner(args, REPO_ROOT, True)
    return result.returncode, result.stdout


def _state(runner: Runner, cid: str) -> dict | None:
    """The container's State as a dict, or None when docker can't inspect it."""
    code, out = _output(runner, ["docker", "inspect", "--format", "{{json .State}}", cid])
    if code != 0:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _fail(runner: Runner, message: str, cid: str) -> int:
    print(f"::error::{message}")
    runner(["docker", "logs", cid], REPO_ROOT, False)
    return 1


def check_container(name: str, cid: str, runner: Runner, sleep: Callable[[float], None], tries: int, interval: float, grace: float) -> int:
    state = _state(runner, cid)
    if state is None:
        return _fail(runner, f"{name}: docker couldn't inspect container {cid}", cid)
    if "Health" not in state:
        # No healthcheck defined: a weaker signal, but it still catches an
        # immediate crash-loop or bad entrypoint.
        sleep(grace)
        state = _state(runner, cid)
        if state is None or state.get("Running") is not True:
            return _fail(runner, f"{name} exited unexpectedly", cid)
        return 0

    print(f"Waiting for {name} to report healthy...")
    status = state["Health"].get("Status")
    for attempt in range(tries):
        if status == "healthy":
            return 0
        if status == "unhealthy":
            return _fail(runner, f"{name} is unhealthy", cid)
        if attempt < tries - 1:
            sleep(interval)
            state = _state(runner, cid)
            if state is None:
                return _fail(runner, f"{name}: docker couldn't inspect container {cid}", cid)
            status = state.get("Health", {}).get("Status")
    return _fail(runner, f"{name} never became healthy (last: {status})", cid)


def wait_for_stack(
    compose_file: str,
    runner: Runner = run,
    sleep: Callable[[float], None] = time.sleep,
    tries: int = POLL_TRIES,
    interval: float = POLL_INTERVAL,
    grace: float = NO_HEALTHCHECK_GRACE,
) -> int:
    code, out = _output(runner, ["docker", "compose", "-f", compose_file, "config", "--services"])
    if code != 0:
        print(f"::error::docker compose config --services failed for {compose_file}")
        return code
    for service in out.split():
        code, out = _output(runner, ["docker", "compose", "-f", compose_file, "ps", "-q", service])
        containers = out.split()
        if code != 0 or not containers:
            print(f"::error::{service} never started")
            return 1
        for cid in containers:
            result = check_container(service, cid, runner, sleep, tries, interval, grace)
            if result != 0:
                return result
    return 0


def main(argv: list[str] | None = None, runner: Runner = run, sleep: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("compose_file")
    args = parser.parse_args(argv)
    return wait_for_stack(args.compose_file, runner, sleep)


if __name__ == "__main__":
    sys.exit(main())
