"""Prove a freshly-minted leaf key can actually do its job over the same
rclone S3-compatible path production uses, before an old key is ever
revoked. Used by create_leaf_keys.py's --rotate flow across all three
providers.
"""
from __future__ import annotations

import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Unique per verification, never reused: confirmed live that reusing
# one fixed path breaks permanently the moment a bucket has a retention
# rule — the first write creates the object, every later write to that
# same key is a genuine RetentionRuleViolation, not a permissions or
# propagation issue, and it never resolves by waiting. A fresh key
# avoids that entirely, and better matches production anyway (cloud_sync
# uses `rclone copy`, never `sync` — always new objects, never
# overwrites, per this doc's Threat model section). The write leaf
# deliberately has no delete capability on either provider (see this
# doc), so these accumulate forever — accepted cost, since rotations are
# rare and each marker is a few bytes.
def _verify_marker_key(leaf: str) -> str:
    # time.time_ns() + a random suffix, not just second-resolution
    # time.time() — two verifications in the same second must not
    # collide and silently reintroduce the exact bug this exists to
    # avoid (see this function's header comment).
    return f"_rotation-verify/{leaf}-{time.time_ns()}-{secrets.token_hex(4)}"


# A brand-new leaf credential isn't always usable by the provider's
# S3-compat API the instant the create call returns (confirmed live on
# OCI and R2, different HTTP status per provider — see
# docs/cloud-credential-creation.md's Rotation section for specifics).
# Retried broadly on status alone, not specific error text, since
# neither provider distinguishes "not propagated yet" from "genuinely
# denied by policy" in the response — a real policy problem now also
# takes the full window to surface as a failure, accepted because the
# alternative (no retry) orphans a fresh credential on every manual
# re-run instead.
_PROPAGATION_ERROR_MARKERS = ("StatusCode: 403", "StatusCode: 401")


def _run_rclone_with_retry(cmd: list[str], timeout: int, retries: int = 60, delay: int = 15) -> subprocess.CompletedProcess:
    result = None
    for attempt in range(1, retries + 1):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result
        if attempt < retries and any(marker in result.stderr for marker in _PROPAGATION_ERROR_MARKERS):
            elapsed = attempt * delay
            print(f"  (new key not yet recognized by the provider, attempt {attempt}/{retries}, ~{elapsed}s elapsed — retrying in {delay}s)", file=sys.stderr)
            time.sleep(delay)
            continue
        break
    return result


def verify_leaf_via_rclone(
    access_key: str, secret_key: str, endpoint: str, region: str, bucket: str, leaf: str, timeout: int = 45
) -> tuple[bool, str]:
    """Prove a freshly-minted leaf key can do its actual job over the same
    rclone S3-compatible path cloud_sync/restore-discovery use in
    production — not just that the provider's native API accepts it
    (see docs/cloud-credential-creation.md's B2 section for why that
    distinction matters).

    read: a real ListObjectsV2 (`rclone lsjson`). write: a real PutObject
    (`rclone copyto`) to a fresh, uniquely-named marker key (see
    _verify_marker_key) — rclone's S3 backend does its own pre-flight
    HeadObject before the upload either way, so this exercises both
    calls the write leaf actually needs. Returns (ok, detail).

    `region` and `no_check_bucket = true` are both required, not
    optional, and retries run through a real provider propagation
    window — see docs/cloud-credential-creation.md's Rotation section
    for what breaks without each of these and why the retry gate is as
    broad as it is.
    """
    with tempfile.TemporaryDirectory() as tmp:
        conf_path = Path(tmp) / "rclone.conf"
        conf_path.write_text(
            "[verify]\n"
            "type = s3\n"
            "provider = Other\n"
            f"access_key_id = {access_key}\n"
            f"secret_access_key = {secret_key}\n"
            f"endpoint = {endpoint}\n"
            f"region = {region}\n"
            "force_path_style = true\n"
            "no_check_bucket = true\n"
        )
        conf_path.chmod(0o600)
        cmd = ["rclone", "--config", str(conf_path), "--contimeout", "5s", "--timeout", f"{timeout}s", "--low-level-retries", "1"]

        if leaf == "read":
            result = _run_rclone_with_retry([*cmd, "lsjson", f"verify:{bucket}", "--max-depth", "1"], timeout)
            if result.returncode != 0:
                return False, f"rclone lsjson (ListObjectsV2) failed: {result.stderr.strip()}"
            return True, "ListObjectsV2 succeeded"

        marker_path = Path(tmp) / "marker.txt"
        marker_path.write_text(f"homelab rotation-verify marker for the {leaf} leaf\n")
        result = _run_rclone_with_retry(
            [*cmd, "copyto", str(marker_path), f"verify:{bucket}/{_verify_marker_key(leaf)}"], timeout
        )
        if result.returncode != 0:
            return False, f"rclone copyto (PutObject) failed: {result.stderr.strip()}"
        return True, "PutObject succeeded"
