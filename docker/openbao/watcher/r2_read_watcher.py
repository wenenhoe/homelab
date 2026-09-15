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

`docker logs -f` with no `--since` replays the container's entire
retained log history before following live, so every process restart
would otherwise re-alert on every past real read. STATE_PATH persists
the last-alerted match's time and request id; on startup that time is
passed as `--since`. Confirmed live: `--since <T>` is inclusive of a
line timestamped exactly `T`, so the request id is also checked to
skip re-alerting on that one boundary line - the timestamp alone
isn't enough to tell "the same read again" from "a new read in the
same nanosecond" apart.

Requires Python >=3.14 for the unparenthesized `except A, B:` below
(PEP change: allowed without an `as` clause). Fails to import on
earlier versions.

Uses hvac for the OpenBao client - see
docs/projects/openbao-python-client-hardening.md, Stage 4. No
paramiko/SSH involved here, unlike cache.py/bootstrap_secrets.py:
this runs directly on `security` itself (see OPENBAO_BASE_URL below),
so there's no remote root-cert fetch to make - `verify=False` is the
loopback TLS trust, not a paramiko host-key one. Also no reconnect/
token-renewal concern: the Vault login happens once at startup to
fetch Telegram's secrets, and `watch()` below never receives or reuses
that token - a stale/expired token past that point is irrelevant since
nothing ever presents it again.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

import hvac
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # hvac.Client(verify=False) below is deliberate (loopback), silence its warning

TARGET_PATH = "secret/data/cloud_credentials/rotation/_rotation-key-cloudflare-r2-token"
OPENBAO_BASE_URL = "https://127.0.0.1:8200"  # loopback, same host - see docs/openbao-r2-read-watcher.md
ROLE_ID_PATH = "/etc/r2-read-watcher/role_id"
SECRET_ID_PATH = "/etc/r2-read-watcher/secret_id"  # noqa: S105 - file path, not a secret value
TELEGRAM_VAULT_SCOPE = "hosts/all/telegram"  # ADR 0021
VAULT_KV_MOUNT = "secret"
STATE_PATH = "/var/lib/r2-read-watcher/state.json"
# Bounds the hvac.Client - see cloud_credentials/cache.py's identical
# constant/comment.
_TIMEOUT_SECONDS = 10


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
        "request_id": request.get("id", "unknown"),
        "role_name": metadata.get("role_name", "unknown"),
        "display_name": auth.get("display_name", "unknown"),
        "remote_address": request.get("remote_address", "unknown"),
    }


def _read_file(path: str) -> str:
    with open(path) as f:
        return f.read().strip()


def _load_state(path: str) -> dict[str, str] | None:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _save_state(path: str, match: dict[str, Any]) -> None:
    """Writes {time, request_id} atomically (tmp file + rename) so a
    crash mid-write can't leave a truncated state file."""
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump({"time": match["time"], "request_id": match["request_id"]}, f)
    os.replace(tmp_path, path)


def _vault_login(client: hvac.Client, role_id: str, secret_id: str) -> None:
    client.auth.approle.login(role_id=role_id, secret_id=secret_id)


def _read_vault_secret(client: hvac.Client, name: str) -> str | None:
    try:
        resp = client.secrets.kv.v2.read_secret_version(
            path=f"{TELEGRAM_VAULT_SCOPE}/{name}",
            mount_point=VAULT_KV_MOUNT,
            # See cloud_credentials/cache.py's identical call/comment -
            # preserves current behavior, silences hvac's v3.0.0
            # default-change warning.
            raise_on_deleted_version=True,
        )
    except hvac.exceptions.InvalidPath:
        return None
    return resp["data"]["data"]["value"]


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


def _fetch_telegram_secrets(client: hvac.Client) -> dict[str, str] | None:
    tg_token = _read_vault_secret(client, "telegram-token")
    chat_id = _read_vault_secret(client, "telegram-chat-id")
    if not tg_token or not chat_id:
        print("telegram-token/telegram-chat-id not cached - watcher will run but can't alert", file=sys.stderr)
        return None
    return {
        "token": tg_token,
        "chat_id": chat_id,
        "topic_id": _read_vault_secret(client, "telegram-topic-id-backups") or "",
    }


def watch(telegram: dict[str, str] | None, prior_state: dict[str, str] | None) -> int:
    docker_logs_cmd = ["docker", "logs", "-f"]
    if prior_state is not None:
        docker_logs_cmd += ["--since", prior_state["time"]]
    docker_logs_cmd.append("openbao")

    proc = subprocess.Popen(
        docker_logs_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdout is None:
        raise RuntimeError("Popen with stdout=PIPE should always set stdout")

    skip_request_id = prior_state["request_id"] if prior_state is not None else None
    for line in proc.stdout:
        match = match_r2_read(line)
        if match is None:
            continue
        if skip_request_id is not None and match["request_id"] == skip_request_id:
            skip_request_id = None  # --since is inclusive; this is that boundary line, not a new read
            continue
        print(f"R2 admin token read: {match}", file=sys.stderr)
        if telegram is not None:
            send_alert(telegram, match)
        _save_state(STATE_PATH, match)
    return proc.wait()


def main() -> int:
    role_id = _read_file(ROLE_ID_PATH)
    secret_id = _read_file(SECRET_ID_PATH)
    client = hvac.Client(url=OPENBAO_BASE_URL, verify=False, timeout=_TIMEOUT_SECONDS)
    _vault_login(client, role_id, secret_id)
    telegram = _fetch_telegram_secrets(client)
    prior_state = _load_state(STATE_PATH)
    return watch(telegram, prior_state)


if __name__ == "__main__":
    raise SystemExit(main())
