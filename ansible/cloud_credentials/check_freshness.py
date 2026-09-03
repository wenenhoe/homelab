#!/usr/bin/env python3
"""Read every leaf credential's and rotation key's/token's expiry -
native where a provider reports one, self-tracked (see expiry.py)
where it doesn't - and alert if anything is already past its window.

Runs unattended, on a schedule, same three-outcome shape as
backup_agent's check-freshness.sh (see docs/uptime-kuma.md and
ADR 0015 for why the same split applies here):

    fresh                              -> no alert
    past its window (checked fine)     -> alert, but this run still exits 0
    couldn't check at all (auth/HTTP)  -> alert AND a nonzero exit

Collapsing the last two would alert on ordinary quarterly expiry (the
whole point of this script) exactly like an actual outage - only a
genuine check failure should ever make the run itself fail.

Deliberately never prompts (see r2_rotation_token's own interactive
path in leaf_keys/r2.py) - this runs from a systemd timer with no TTY,
so a missing R2 rotation-token cache file is reported as a check
failure for R2's two entries, not a hang.

Usage (run from ansible/):
    python3 -m cloud_credentials.check_freshness
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import requests

from cloud_credentials.cache import cached, read_cache
from cloud_credentials.expiry import is_expired
from cloud_credentials.leaf_keys.b2 import B2_LEAF_CAPABILITIES, b2_list_keys, b2_rotation_session

FRESH, STALE, CHECK_FAILED = "fresh", "past its window", "check failed"


def _report(name: str, status: str, detail: str = "") -> str:
    line = f"{name}: {status}"
    return f"{line} ({detail})" if detail else line


def check_b2() -> list[tuple[str, str, str]]:
    """One b2_list_keys call covers both leaves and the rotation key
    itself - all three names are known ahead of time, no per-key
    lookup needed."""
    try:
        session, account_id, api_url = b2_rotation_session()
        keys_by_name = {k["keyName"]: k for k in b2_list_keys(session, api_url, account_id)}
    except (requests.HTTPError, SystemExit) as exc:
        detail = str(exc)
        return [(f"b2 {name}", CHECK_FAILED, detail) for name in (*B2_LEAF_CAPABILITIES, "rotation key")]

    results = []
    for leaf in B2_LEAF_CAPABILITIES:
        key = keys_by_name.get(f"homelab-cloud-sync-{leaf}")
        results.append(_b2_key_result(f"b2 {leaf}", key))
    results.append(_b2_key_result("b2 rotation key", keys_by_name.get("homelab-cloud-sync-rotation-key")))
    return results


def _b2_key_result(label: str, key: dict | None) -> tuple[str, str, str]:
    if key is None:
        return (label, CHECK_FAILED, "no matching key found on the account")
    expiration_ms = key.get("expirationTimestamp")
    if expiration_ms is None:
        return (label, CHECK_FAILED, "key has no expirationTimestamp - was it created before this rotated in?")
    if time.time() * 1000 >= expiration_ms:
        return (label, STALE, f"expired at epoch ms {expiration_ms}")
    return (label, FRESH, "")


def check_oci() -> list[tuple[str, str, str]]:
    results = []
    for leaf in ("write", "read"):
        results.append(_oci_created_at_result(f"oci {leaf}", f"oci-{leaf}-created-at"))
    results.append(_oci_created_at_result("oci rotation keypair", "_rotation-key-oci-created-at"))
    return results


def _oci_created_at_result(label: str, cache_name: str) -> tuple[str, str, str]:
    if not cached(cache_name):
        return (label, CHECK_FAILED, f"no {cache_name} cache file - created before this thread's tracking was added?")
    created_at = read_cache(cache_name)
    return (label, STALE, f"created {created_at}") if is_expired(created_at) else (label, FRESH, "")


def check_r2() -> list[tuple[str, str, str]]:
    token = read_cache("_rotation-key-cloudflare-r2-token")
    account_id = read_cache("cloudflare-r2-account-id")
    if token is None or account_id is None:
        missing = "rotation token" if token is None else "account id"
        detail = f"no cached {missing} - can't query Cloudflare without prompting"
        return [(f"r2 {name}", CHECK_FAILED, detail) for name in ("write", "read", "rotation token")]

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    results = []
    for leaf in ("write", "read"):
        token_id = read_cache(f"cloudflare-r2-{leaf}-access-key")
        results.append(_r2_get_token_result(f"r2 {leaf}", session, account_id, token_id))

    verify = session.get(f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/verify").json()
    if not verify.get("success"):
        results.append(("r2 rotation token", CHECK_FAILED, str(verify.get("errors"))))
    else:
        results.append(_r2_expires_on_result("r2 rotation token", verify["result"].get("expires_on")))
    return results


def _r2_get_token_result(label: str, session: requests.Session, account_id: str, token_id: str | None) -> tuple[str, str, str]:
    if token_id is None:
        return (label, CHECK_FAILED, "no cached token id")
    resp = session.get(f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/{token_id}").json()
    if not resp.get("success"):
        return (label, CHECK_FAILED, str(resp.get("errors")))
    return _r2_expires_on_result(label, resp["result"].get("expires_on"))


def _r2_expires_on_result(label: str, expires_on: str | None) -> tuple[str, str, str]:
    if expires_on is None:
        return (label, CHECK_FAILED, "token has no expires_on - created before this thread's expiry was added?")
    expires_at = datetime.fromisoformat(expires_on.replace("Z", "+00:00"))
    return (label, STALE, f"expired at {expires_on}") if datetime.now(UTC) >= expires_at else (label, FRESH, "")


def main() -> int:
    all_results = [*check_b2(), *check_oci(), *check_r2()]
    had_check_failure = False
    for name, status, detail in all_results:
        print(_report(name, status, detail))
        if status == CHECK_FAILED:
            had_check_failure = True

    return 1 if had_check_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
