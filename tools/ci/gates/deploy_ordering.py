#!/usr/bin/env python3
"""The deploy-ordering-check job's two playbook runs, and the verdict on the second.

Regression coverage for an incident where `ansible_host` was wired to
resolve through a role-generated fact (`secrets_generated`) without
anything in CI exercising that chain — see docs/ci.md#deploy-ordering-check.
Both runs use the purpose-built inventory, so they touch no real host.

`deploy` runs the real deploy.yaml with `--tags` matching nothing real, so
provisioning is filtered out while Gathering Facts and the secrets tasks
(tags: [always]) still run. `--limit` includes localhost because Play 0
targets `hosts: localhost`, which `--limit ci-managed-host` alone would skip.

`restore` runs bootstrap-secrets.yaml and restore.yaml as one two-file
invocation, the pattern restore.yaml needs (see docs/restore.md), against a
nonexistent archive. The run must fail, and fail at the archive-existence
check; classify_restore turns the exit code and log into a verdict:

- a log carrying the ansible_host resolution failure means the regression
  is back;
- success means something unrelated changed;
- failure without the role's own archive-not-found message means it failed
  somewhere else.

Usage (from tools/): python -m ci.gates.deploy_ordering {deploy|restore}
Expects the registry override from ci.fixtures.strip_vault_scope at
/tmp/ci-secrets-registry-no-vault.json.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ANSIBLE_DIR = REPO_ROOT / "ansible"

INVENTORY = "inventory/ci-deploy-ordering-inventory.yaml"
REGISTRY_OVERRIDE = "@/tmp/ci-secrets-registry-no-vault.json"
LIMIT = "ci-managed-host,localhost"

# What an unresolved ansible_host looks like in the log. Matched per line,
# so `secrets_generated` and `undefined` must share a line.
RESOLUTION_FAILURE = re.compile(r"remote_addr|secrets_generated.*undefined")
# ansible/roles/restore/tasks/main.yaml's own failure message for a missing archive.
EXPECTED_FAILURE = "not found on the controller"

DEPLOY_ARGS = [
    "ansible-playbook",
    "-i",
    INVENTORY,
    "playbooks/deploy.yaml",
    "--tags",
    "ci-deploy-ordering-check-tag-matches-nothing",
    "--limit",
    LIMIT,
    "-e",
    "compose_deploy_dir=/tmp/compose-deploy-ordering-check",
    "-e",
    REGISTRY_OVERRIDE,
]
RESTORE_ARGS = [
    "ansible-playbook",
    "-i",
    INVENTORY,
    "playbooks/bootstrap-secrets.yaml",
    "playbooks/restore.yaml",
    "--limit",
    LIMIT,
    "-e",
    "restore_app=ci-ordering-check-app",
    "-e",
    "restore_archive_local_path=/nonexistent/ci-ordering-check-archive.tar.gz",
    "-e",
    'restore_volumes=["ci_ordering_check_data"]',
    "-e",
    REGISTRY_OVERRIDE,
]

# (args, cwd, capture) -> result. capture=False lets the child write straight
# to this process's stdout/stderr, so a long run streams into the job log;
# capture=True returns stdout and stderr merged, in order, for the verdict.
Runner = Callable[[list[str], Path, bool], "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class Verdict:
    ok: bool
    message: str


def classify_restore(returncode: int, log: str) -> Verdict:
    """The verdict on the restore run's exit code and combined output."""
    if RESOLUTION_FAILURE.search(log):
        return Verdict(False, "ansible_host never resolved for restore.yaml's two-file invocation — the ordering regression this check exists to catch.")
    if returncode == 0:
        return Verdict(False, "Expected a failure at the archive-existence check (nonexistent path) — succeeded instead, meaning something unrelated changed.")
    if EXPECTED_FAILURE not in log:
        return Verdict(False, "Failed, but not with the expected archive-not-found message — see log above.")
    return Verdict(True, "OK: reached the expected, safe archive-not-found failure — ansible_host resolved correctly.")


def _run(args: list[str], cwd: Path, capture: bool) -> subprocess.CompletedProcess[str]:
    if capture:
        return subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    return subprocess.run(args, cwd=cwd, text=True, check=False)


def run_deploy(run: Runner = _run) -> int:
    return run(DEPLOY_ARGS, ANSIBLE_DIR, False).returncode


def run_restore(run: Runner = _run) -> int:
    result = run(RESTORE_ARGS, ANSIBLE_DIR, True)
    log = result.stdout
    print(log)
    verdict = classify_restore(result.returncode, log)
    if verdict.ok:
        print(verdict.message)
        return 0
    print(f"::error::{verdict.message}")
    return 1


def main(argv: list[str] | None = None, run: Runner = _run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", choices=["deploy", "restore"])
    args = parser.parse_args(argv)
    return run_deploy(run) if args.mode == "deploy" else run_restore(run)


if __name__ == "__main__":
    sys.exit(main())
