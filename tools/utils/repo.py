"""Generic repo-navigation and homelab-wide bootstrap helpers - none
of this is OpenBao/Vault-specific, even though openbao_utils.client
is currently its only consumer. PROJECT_ROOT/SECRETS_DIR/main_domain()
are used for main-domain and any other manual secret
openbao_utils/bootstrap.py prompts for, not just OpenBao's own
role-id/secret-id; security_ssh_target()/fetch_root_cert() are plain
"SSH to security, read step-ca's shared root cert" - nothing in either
one touches OpenBao's API. See
docs/decisions/0031-where-repo-tooling-lives/revision-000.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import paramiko
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SECRETS_DIR = PROJECT_ROOT / "ansible/files/secrets"
INVENTORY_PATH = PROJECT_ROOT / "ansible/inventory/inventory.yaml"

STEP_CA_CONTAINER = "step-ca"
# Bounds both the SSH root-cert fetch and every Vault HTTP call built
# on top of it - one number to reason about, not a fresh one per
# caller. The SSH fetch previously had no timeout at all in either of
# openbao_utils.client's two original callers (the bug
# docs/decisions/0030-openbao-client-implementation-in-repo-python/revision-000.md fixed).
TIMEOUT_SECONDS = 10


def read_bootstrap_file(name: str) -> str | None:
    """main-domain, openbao-controller-role-id/-secret-id, and any
    other manual secret whose own access something else depends on
    live permanently in this file cache instead, read directly from
    SECRETS_DIR, never through Vault - they can't live in the thing
    they unlock."""
    path = SECRETS_DIR / name
    return path.read_text().strip() if path.exists() else None


def main_domain() -> str:
    domain = read_bootstrap_file("main-domain")
    if not domain:
        print(
            "main-domain isn't cached yet - it's needed to reach OpenBao at all "
            "(secrets_registry.yaml's header comment explains why it never moves "
            "into Vault). Set it first:\n"
            f"  printf '%s' '<your-domain>' > {SECRETS_DIR / 'main-domain'}\n"
            f"  chmod 600 {SECRETS_DIR / 'main-domain'}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return domain


def security_ssh_target() -> tuple[str, str, str]:
    """(user, host, key_path) for SSH to `security`, read from
    inventory.yaml rather than hardcoded twice."""
    with INVENTORY_PATH.open() as f:
        inv = yaml.safe_load(f)
    user = inv["all"]["children"]["managed_hosts"]["hosts"]["security"]["ansible_user"]
    key_path = Path(inv["all"]["vars"]["ansible_ssh_private_key_file"]).expanduser()
    host = f"security.internal.{main_domain()}"  # ddns_domain, see inventory.yaml
    return user, host, str(key_path)


def fetch_root_cert() -> str:
    user, host, key_path = security_ssh_target()
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    # Trust-on-first-use, same as the previous StrictHostKeyChecking=
    # accept-new: system known_hosts is checked first, and paramiko's
    # transport still raises BadHostKeyException on a mismatch against
    # an already-known host regardless of this policy - fail-closed on
    # a changed key, not blanket trust. Confirmed live against a real
    # host - see docs/decisions/0030-openbao-client-implementation-in-repo-python/revision-000.md.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=user, key_filename=key_path, timeout=TIMEOUT_SECONDS)
        _stdin, stdout, stderr = client.exec_command(
            f"docker exec {STEP_CA_CONTAINER} cat /home/step/certs/root_ca.crt",
            timeout=TIMEOUT_SECONDS,
        )
        cert = stdout.read().decode()
        err = stderr.read().decode()
        exit_status = stdout.channel.recv_exit_status()
    finally:
        client.close()
    if exit_status != 0:
        print(f"Failed to fetch step-ca's root cert from {host}: {err}", file=sys.stderr)
        raise SystemExit(1)
    return cert
