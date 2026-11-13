#!/usr/bin/env python3
"""Fails when .github/renovate.json5 is not a valid Renovate repository config.

Renovate stops every pull request while its config is invalid, and the config is
only read by the scheduled run, so an error reaches `main` unseen. This runs
`renovate-config-validator --strict --no-global` from the Renovate image that
renovate.yml pins, so the config is judged by the version that will read it, with the
regex engine (RE2) that version uses. `--no-global` is needed because the validator
otherwise treats a named file as a self-hosted global config, not a repository's.
`--strict` also fails a config that needs migrating.

Needs Docker and nothing else. The container has no network, so every preset the config
extends must be one Renovate ships.

Usage (from tools/): python -m ci.gates.renovate_config

Exit status: 0 when the config is valid, 1 when the validator rejects it, 2 when no
verdict was reached (the pin cannot be read, or Docker could not run the image).
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG = ".github/renovate.json5"
WORKFLOW = ".github/workflows/renovate.yml"
IMAGE = "ghcr.io/renovatebot/renovate"
PULL_TIMEOUT = 600
RUN_TIMEOUT = 120
# `docker run` exits with these when docker itself failed, not the validator in the container.
DOCKER_FAILED = (125, 126, 127)
CONTAINER_CONFIG = "/config/renovate.json5"

_PIN = re.compile(r'^\s*renovate-version:\s*"(?P<pin>[^"]*)"\s*$', re.MULTILINE)
_PIN_SHAPE = re.compile(r"\d+\.\d+\.\d+(?:@sha256:[a-f0-9]{64})?")
# Named, not written inline: `ruff format` targets 3.14 and drops the parentheses from a bare
# `except (A, B):`, which older Pythons (the runner's python3) can't parse.
_RUN_ERRORS = (OSError, subprocess.TimeoutExpired)

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class NoVerdict(Exception):
    """The config cannot be given a verdict: the pin is unreadable or Docker could not run the image."""


def pinned_image(workflow_text: str) -> str:
    """The image reference the Renovate workflow runs, `ghcr.io/renovatebot/renovate:<version>[@sha256:...]`."""
    pins = [match["pin"] for match in _PIN.finditer(workflow_text)]
    if len(pins) != 1:
        raise NoVerdict(f"{WORKFLOW} must set `renovate-version` exactly once, found {len(pins)}")
    if not _PIN_SHAPE.fullmatch(pins[0]):
        raise NoVerdict(f"{WORKFLOW}: `renovate-version` is {pins[0]!r}, not <major>.<minor>.<patch> with an optional @sha256 digest")
    return f"{IMAGE}:{pins[0]}"


def validator_args(image: str, config: Path) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--mount",
        f"type=bind,source={config},target={CONTAINER_CONFIG},readonly",
        image,
        "renovate-config-validator",
        "--strict",
        "--no-global",
        CONTAINER_CONFIG,
    ]


def pull(image: str, runner: Runner = subprocess.run) -> None:
    try:
        result = runner(["docker", "pull", "--quiet", image], capture_output=True, text=True, timeout=PULL_TIMEOUT, check=False)
    except _RUN_ERRORS as exc:
        raise NoVerdict(f"cannot pull {image}: {exc}") from exc
    if result.returncode != 0:
        reason = result.stderr.strip().splitlines()[-1:] or [f"exit status {result.returncode}"]
        raise NoVerdict(f"cannot pull {image}: {reason[0]}")


def validate(image: str, config: Path, runner: Runner = subprocess.run) -> str | None:
    """None when the validator accepts the config, else everything it printed."""
    try:
        result = runner(validator_args(image, config), capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise NoVerdict(f"the validator did not finish within {RUN_TIMEOUT} seconds") from None
    except OSError as exc:
        raise NoVerdict(f"cannot run docker: {exc}") from exc
    if result.returncode in DOCKER_FAILED:
        raise NoVerdict(f"docker could not run {image} (exit status {result.returncode}): {result.stderr.strip()}")
    if result.returncode == 0:
        return None
    return (result.stdout + result.stderr).strip() or f"exit status {result.returncode}"


def check(root: Path, runner: Runner = subprocess.run) -> str | None:
    """None when the config at `root` is valid under the pinned Renovate, else the validator's output."""
    config = root / CONFIG
    if not config.is_file():
        raise NoVerdict(f"{CONFIG} does not exist")
    image = pinned_image((root / WORKFLOW).read_text())
    pull(image, runner)
    return validate(image, config.resolve(), runner)


def main(root: Path = REPO_ROOT, runner: Runner = subprocess.run) -> int:
    try:
        problems = check(root, runner)
    except (NoVerdict, OSError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2
    if problems is None:
        print(f"{CONFIG} is valid under the Renovate version {WORKFLOW} pins.")
        return 0
    print(problems)
    print(f"::error file={CONFIG}::the pinned Renovate rejects this config; it would stop every pull request", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
