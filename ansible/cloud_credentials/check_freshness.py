#!/usr/bin/env python3
"""Read every leaf credential's and rotation key's/token's expiry -
native where a provider reports one, self-tracked (see expiry.py)
where it doesn't - and alert on Telegram once anything is expiring
soon, already past its window, or couldn't be checked at all.

Runs unattended, on a schedule. Four checked-fine outcomes, not two -
see ADR 0015's Consequences for why a binary fresh/stale split isn't
enough: B2/R2 enforce their own expiry server-side, so by the time a
credential is STALE there, cloud_sync is already broken. WARNING and
URGENT are the two outcomes that buy any lead time - 30 days and 14
days out respectively, so the reminder escalates as the deadline gets
closer instead of a single cliff edge.

    fresh                              -> no alert
    expiring within WARNING_DAYS (30)  -> Telegram alert, exit 0
    expiring within URGENT_DAYS (14)   -> Telegram alert, exit 0
    already past its window            -> Telegram alert, exit 0
    couldn't check at all (auth/HTTP)  -> Telegram alert, exit 1

The exit code only reflects whether the check itself is healthy, not
whether a credential is due - that's what the Telegram message is for.
Collapsing that distinction would make `systemctl --user status` (and
anything watching this unit's own state) flag ordinary quarterly
expiry the same way it flags a broken check.

Deliberately never prompts (see r2_rotation_token's own interactive
path in leaf_keys/r2.py) - this runs from a systemd timer with no TTY,
so a missing R2 rotation-token cache file is reported as a check
failure for R2's two entries, not a hang.

Usage (run from ansible/):
    python3 -m cloud_credentials.check_freshness
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import requests

from cloud_credentials.cache import cached, read_cache
from cloud_credentials.expiry import QUARTERLY_DAYS, URGENT_DAYS, WARNING_DAYS
from cloud_credentials.leaf_keys.b2 import B2_LEAF_CAPABILITIES, b2_list_keys, b2_rotation_session

FRESH, WARNING, URGENT, STALE, CHECK_FAILED = "fresh", "expiring soon", "expiring very soon", "past its window", "check failed"


def _report(name: str, status: str, detail: str = "") -> str:
    line = f"{name}: {status}"
    return f"{line} ({detail})" if detail else line


def _classify(expires_at: datetime) -> tuple[str, str]:
    """The one place fresh/warning/urgent/stale gets decided, so
    B2/R2/OCI - ms-epoch, RFC 3339, and self-tracked ISO respectively -
    all land on the same two thresholds instead of three copies
    drifting apart. Checked tightest-first: a credential inside
    URGENT_DAYS is also inside WARNING_DAYS, so the order matters."""
    now = datetime.now(UTC)
    if now >= expires_at:
        return STALE, f"expired {expires_at.isoformat()}"
    days_left = (expires_at - now).days
    if days_left <= URGENT_DAYS:
        return URGENT, f"expires in {days_left}d ({expires_at.isoformat()})"
    if days_left <= WARNING_DAYS:
        return WARNING, f"expires in {days_left}d ({expires_at.isoformat()})"
    return FRESH, ""


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
    status, detail = _classify(datetime.fromtimestamp(expiration_ms / 1000, tz=UTC))
    return (label, status, detail)


def check_oci() -> list[tuple[str, str, str]]:
    results = []
    for leaf in ("write", "read"):
        results.append(_oci_created_at_result(f"oci {leaf}", f"oci-{leaf}-created-at"))
    results.append(_oci_created_at_result("oci rotation keypair", "_rotation-key-oci-created-at"))
    return results


def _oci_created_at_result(label: str, cache_name: str) -> tuple[str, str, str]:
    if not cached(cache_name):
        return (label, CHECK_FAILED, f"no {cache_name} cache file - created before this thread's tracking was added?")
    created_at = datetime.fromisoformat(read_cache(cache_name))
    status, detail = _classify(created_at + timedelta(days=QUARTERLY_DAYS))
    return (label, status, detail)


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
    status, detail = _classify(datetime.fromisoformat(expires_on.replace("Z", "+00:00")))
    return (label, status, detail)


def _send_telegram_alert(lines: list[str]) -> None:
    """Same secrets, same directory, same Telegram Bot API call
    `telegram_notify` (ansible/roles/telegram_notify) already makes for
    every other consumer in this repo - just not through that role,
    since it's Ansible-templated and deployed to `managed_hosts`, and
    `controller` (where this actually runs - see ADR 0015) deliberately
    isn't one. See docs/telegram-notifications.md for the shared
    conventions (topic routing, Markdown escaping rules) this follows."""
    token = read_cache("telegram-token")
    chat_id = read_cache("telegram-chat-id")
    if not token or not chat_id:
        print("telegram: no telegram-token/telegram-chat-id cached, alert not sent:\n" + "\n".join(lines), file=sys.stderr)
        return

    topic_id = read_cache("telegram-topic-id-backups")
    data = {
        "chat_id": chat_id,
        "text": "*cloud_credentials freshness check*\n\n" + "\n".join(lines),
        "parse_mode": "Markdown",
    }
    if topic_id:
        # Telegram's API rejects this param outright if passed empty
        # rather than ignoring it - only include it when actually set.
        data["message_thread_id"] = topic_id

    try:
        resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"telegram: alert send failed: {exc}", file=sys.stderr)


def main() -> int:
    all_results = [*check_b2(), *check_oci(), *check_r2()]
    had_check_failure = False
    alert_lines = []

    for name, status, detail in all_results:
        print(_report(name, status, detail))
        if status == CHECK_FAILED:
            had_check_failure = True
        if status != FRESH:
            alert_lines.append(f"*{name}*: {status}" + (f" — {detail}" if detail else ""))

    if alert_lines:
        _send_telegram_alert(alert_lines)

    return 1 if had_check_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
