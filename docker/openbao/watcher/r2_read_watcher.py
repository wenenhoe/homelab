#!/usr/bin/env python3
"""ADR 0026's dedicated R2 per-read watcher (ADR 0024's own
requirement). Tails `docker logs -f openbao` (the audit device's
stdout, per ADR 0026), alerts on any read of the R2 rotation token's
Vault path, and does nothing else - no cloud_credentials access, no
write capability, nothing beyond the one path its own AppRole can
read (Telegram's secrets).

Confirmed against a live 2.6.2 audit log (not inferred from docs):
paths are plaintext, values and tokens are HMAC'd, and a single read
produces both a `request`-type and a `response`-type line sharing the
same path - matching on `type == "request"` alone is sufficient and
avoids double-alerting on one real read.

Runs as a persistent systemd service on `security` - see
docs/openbao-r2-read-watcher.md for installation. Logs in once at
startup to fetch Telegram's secrets, then never touches Vault again
for the rest of the process's life; alerting itself is a direct
Telegram Bot API call, not a Vault operation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # verify=False below is deliberate (loopback), silence its per-request warning

TARGET_PATH = "secret/data/cloud_credentials/rotation/_rotation-key-cloudflare-r2-token"
OPENBAO_BASE_URL = "https://127.0.0.1:8200"  # loopback, same host - see docs/openbao-r2-read-watcher.md
ROLE_ID_PATH = "/etc/r2-read-watcher/role_id"
SECRET_ID_PATH = "/etc/r2-read-watcher/secret_id"  # noqa: S105 - file path, not a secret value
TELEGRAM_VAULT_SCOPE = "hosts/all/telegram"  # ADR 0021


def match_r2_read(raw_line: str) -> dict[str, Any] | None:
    """Parses one audit-log line; returns match details if it's a real
    read attempt on the R2 rotation token, else None. Never raises -
    a malformed or unrelated line (docker log noise, a truncated
    write during rotation) is just not a match, not an error."""
    try:
        entry = json.loads(raw_line)
    except json.JSONDecodeError, TypeError:
        return None

    if not isinstance(entry, dict):
        return None

    if entry.get("type") != "request":
        return None

    request = entry.get("request")
    if not isinstance(request, dict):
        return None

    if request.get("path") != TARGET_PATH or request.get("operation") != "read":
        return None

    auth = entry.get("auth") or {}
    metadata = auth.get("metadata") or {}
    return {
        "time": entry.get("time", "unknown"),
        "role_name": metadata.get("role_name", "unknown"),
        "display_name": auth.get("display_name", "unknown"),
        "remote_address": request.get("remote_address", "unknown"),
    }


def _read_file(path: str) -> str:
    with open(path) as f:
        return f.read().strip()


def _vault_login(role_id: str, secret_id: str) -> str:
    resp = requests.post(
        f"{OPENBAO_BASE_URL}/v1/auth/approle/login",
        json={"role_id": role_id, "secret_id": secret_id},
        verify=False,  # noqa: S501 - loopback, same host, see module docstring
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["auth"]["client_token"]


def _read_vault_secret(token: str, name: str) -> str | None:
    resp = requests.get(
        f"{OPENBAO_BASE_URL}/v1/secret/data/{TELEGRAM_VAULT_SCOPE}/{name}",
        headers={"X-Vault-Token": token},
        verify=False,  # noqa: S501 - loopback, same host, see module docstring
        timeout=10,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()["data"]["data"]["value"]


def _escape_telegram_html(text: str) -> str:
    """Same reasoning as check_freshness.py's own escaper: HTML
    parse_mode, not legacy Markdown - only &, <, > are ever special."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_alert(telegram: dict[str, str], match: dict[str, Any]) -> None:
    lines = [
        "<b>R2 admin token read</b>",
        "",
        f"Time: {_escape_telegram_html(match['time'])}",
        f"Role: {_escape_telegram_html(match['role_name'])}",
        f"Auth method: {_escape_telegram_html(match['display_name'])}",
        f"Source: {_escape_telegram_html(match['remote_address'])}",
    ]
    data = {
        "chat_id": telegram["chat_id"],
        "text": "\n".join(lines),
        "parse_mode": "HTML",
    }
    if telegram.get("topic_id"):
        data["message_thread_id"] = telegram["topic_id"]

    try:
        resp = requests.post(f"https://api.telegram.org/bot{telegram['token']}/sendMessage", data=data, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"telegram: alert send failed: {exc}", file=sys.stderr)


def _fetch_telegram_secrets(token: str) -> dict[str, str] | None:
    tg_token = _read_vault_secret(token, "telegram-token")
    chat_id = _read_vault_secret(token, "telegram-chat-id")
    if not tg_token or not chat_id:
        print("telegram-token/telegram-chat-id not cached - watcher will run but can't alert", file=sys.stderr)
        return None
    return {
        "token": tg_token,
        "chat_id": chat_id,
        "topic_id": _read_vault_secret(token, "telegram-topic-id-backups") or "",
    }


def watch(telegram: dict[str, str] | None) -> int:
    proc = subprocess.Popen(
        ["docker", "logs", "-f", "openbao"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdout is None:
        raise RuntimeError("Popen with stdout=PIPE should always set stdout")
    for line in proc.stdout:
        match = match_r2_read(line)
        if match is None:
            continue
        print(f"R2 admin token read: {match}", file=sys.stderr)
        if telegram is not None:
            send_alert(telegram, match)
    return proc.wait()


def main() -> int:
    role_id = _read_file(ROLE_ID_PATH)
    secret_id = _read_file(SECRET_ID_PATH)
    token = _vault_login(role_id, secret_id)
    telegram = _fetch_telegram_secrets(token)
    return watch(telegram)


if __name__ == "__main__":
    raise SystemExit(main())
