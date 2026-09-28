#!/usr/bin/env python3
"""Polls every service in a compose stack until it is healthy, or still running.

Used by _compose-boot-test.yml (compose-boot-test and compose-boot-test-all
call the same reusable workflow). For each service, in order, and stopping
at the first failure:

- no container -> "never started";
- a healthcheck is defined -> poll its status (30 checks, 2s apart): healthy
  passes, unhealthy fails at once, anything else keeps waiting and fails
  after the last check with the final status;
- no healthcheck -> a weaker signal, but it still catches an immediate
  crash-loop or a bad entrypoint: wait a 10s grace period, then require the
  container to still be running.

Every failure prints the container's logs, since the reason is gone once
the job's stack is torn down. A service scaled to several containers has
each one checked.

Usage (from tools/): python -m ci.gates.compose_health <path-to-compose.yaml>
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path

from ci.proc import Runner, run

REPO_ROOT = Path(__file__).resolve().parents[3]
HEALTH_CHECKS = 30
HEALTH_INTERVAL = 2.0
NO_HEALTHCHECK_GRACE = 10.0

Sleep = Callable[[float], None]


class DockerError(Exception):
    """A docker command the check depends on failed."""


def _docker(runner: Runner, args: list[str]) -> str:
    result = runner(["docker", *args], REPO_ROOT, True)
    if result.returncode != 0:
        raise DockerError(f"`docker {' '.join(args)}` exited {result.returncode}")
    return result.stdout.strip()


def _fail(runner: Runner, cid: str, message: str) -> int:
    print(f"::error::{message}")
    runner(["docker", "logs", cid], REPO_ROOT, False)
    return 1


def _wait_healthy(runner: Runner, sleep: Sleep, svc: str, cid: str) -> int:
    print(f"Waiting for {svc} to report healthy...")
    status = ""
    for attempt in range(HEALTH_CHECKS):
        status = _docker(runner, ["inspect", "--format={{.State.Health.Status}}", cid])
        if status == "healthy":
            return 0
        if status == "unhealthy":
            return _fail(runner, cid, f"{svc} is unhealthy")
        if attempt < HEALTH_CHECKS - 1:
            sleep(HEALTH_INTERVAL)
    return _fail(runner, cid, f"{svc} never became healthy (last: {status})")


def _stayed_running(runner: Runner, sleep: Sleep, svc: str, cid: str) -> int:
    sleep(NO_HEALTHCHECK_GRACE)
    if _docker(runner, ["inspect", "--format={{.State.Running}}", cid]) != "true":
        return _fail(runner, cid, f"{svc} exited unexpectedly")
    return 0


def wait(compose_file: str, runner: Runner = run, sleep: Sleep = time.sleep) -> int:
    try:
        services = _docker(runner, ["compose", "-f", compose_file, "config", "--services"]).split()
        for svc in services:
            cids = _docker(runner, ["compose", "-f", compose_file, "ps", "-q", svc]).split()
            if not cids:
                print(f"::error::{svc} never started")
                return 1
            for cid in cids:
                has_healthcheck = _docker(runner, ["inspect", "--format={{if .State.Health}}yes{{end}}", cid]) == "yes"
                check = _wait_healthy if has_healthcheck else _stayed_running
                if check(runner, sleep, svc, cid) != 0:
                    return 1
    except DockerError as exc:
        print(f"::error::{exc}")
        return 1
    return 0


def main(argv: list[str] | None = None, runner: Runner = run, sleep: Sleep = time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("compose_file")
    return wait(parser.parse_args(argv).compose_file, runner, sleep)


if __name__ == "__main__":
    sys.exit(main())
