"""Shared expiry constants and timestamp helpers for cloud_credentials'
create/rotate flows and check_freshness.py.

One window for everything created by this package - leaf credentials
and rotation keys/tokens alike, all providers - so a credential's
actual lifetime always matches what check_freshness.py alerts against.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

QUARTERLY_DAYS = 90

# B2's validDurationInSeconds hard ceiling is 86,400,000 (1000 days) -
# confirmed against Backblaze's own b2_create_key reference. 90 days is
# comfortably under it for both leaf keys and B2's own rotation key.
QUARTERLY_SECONDS = QUARTERLY_DAYS * 24 * 60 * 60


def utcnow_iso() -> str:
    """Now, as an ISO-8601 UTC timestamp - what OCI's self-tracked
    `-created-at` cache files store, since OCI's classic Identity API
    (the one this repo authenticates against) has no expiry field of
    its own to read back later. See ADR 0015."""
    return datetime.now(UTC).isoformat()


def rfc3339_in(days: int) -> str:
    """`days` from now, as the RFC 3339 timestamp Cloudflare's
    `expires_on` token field expects."""
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_expired(created_at_iso: str, window_days: int = QUARTERLY_DAYS) -> bool:
    """True once `window_days` have passed since `created_at_iso`. Used
    for self-tracked credentials only (OCI) - providers with a native
    expiry field are checked against their own reported timestamp
    instead, not this function."""
    created_at = datetime.fromisoformat(created_at_iso)
    return datetime.now(UTC) >= created_at + timedelta(days=window_days)
