"""Unit tests for cloud_credentials.expiry.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta

import pytest
from cloud_credentials import expiry


@pytest.fixture
def utc_plus_8(monkeypatch):
    """The process clock zone set to UTC+8: a helper that reads local time instead of UTC differs from the right answer by eight hours."""
    with monkeypatch.context() as patched:
        patched.setenv("TZ", "XYZ-8")
        time.tzset()
        assert datetime.now().astimezone().utcoffset() == timedelta(hours=8)
        yield
    time.tzset()


class TestExpiry:
    def test_quarterly_seconds_under_b2s_1000_day_ceiling(self):
        # B2's own hard maximum, confirmed against its b2_create_key
        # reference (Maximum: 86400000) — this constant must never
        # silently drift past it.
        assert expiry.QUARTERLY_SECONDS < 86_400_000

    def test_is_expired_false_when_within_window(self):
        created_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        assert not expiry.is_expired(created_at)

    def test_is_expired_true_once_window_passed(self):
        created_at = (datetime.now(UTC) - timedelta(days=expiry.QUARTERLY_DAYS + 1)).isoformat()
        assert expiry.is_expired(created_at)

    def test_rfc3339_in_matches_cloudflares_expected_format(self):
        # Cloudflare's Create Token reference documents expires_on as
        # RFC 3339 date-time — this is the exact shape it returns in its
        # own examples ("2020-01-01T00:00:00Z").
        result = expiry.rfc3339_in(90)
        assert re.search(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", result)

    def test_utcnow_iso_is_the_current_utc_time_with_an_offset(self, utc_plus_8):
        stamp = datetime.fromisoformat(expiry.utcnow_iso())
        assert stamp.utcoffset() == timedelta(0)
        assert abs(datetime.now(UTC) - stamp) < timedelta(seconds=5)

    def test_rfc3339_in_is_the_utc_time_that_many_days_ahead(self, utc_plus_8):
        stamp = datetime.strptime(expiry.rfc3339_in(90), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert abs(datetime.now(UTC) + timedelta(days=90) - stamp) < timedelta(seconds=5)
