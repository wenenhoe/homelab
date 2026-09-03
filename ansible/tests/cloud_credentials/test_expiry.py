"""Unit tests for cloud_credentials.expiry.

Run via `uv run pytest ansible/tests/ -v`.
"""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cloud_credentials import expiry


class ExpiryTests(unittest.TestCase):
    def test_quarterly_seconds_under_b2s_1000_day_ceiling(self):
        # B2's own hard maximum, confirmed against its b2_create_key
        # reference (Maximum: 86400000) — this constant must never
        # silently drift past it.
        self.assertLess(expiry.QUARTERLY_SECONDS, 86_400_000)

    def test_is_expired_false_when_within_window(self):
        created_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        self.assertFalse(expiry.is_expired(created_at))

    def test_is_expired_true_once_window_passed(self):
        created_at = (datetime.now(UTC) - timedelta(days=expiry.QUARTERLY_DAYS + 1)).isoformat()
        self.assertTrue(expiry.is_expired(created_at))

    def test_rfc3339_in_matches_cloudflares_expected_format(self):
        # Cloudflare's Create Token reference documents expires_on as
        # RFC 3339 date-time — this is the exact shape it returns in its
        # own examples ("2020-01-01T00:00:00Z").
        result = expiry.rfc3339_in(90)
        self.assertRegex(result, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


if __name__ == "__main__":
    unittest.main()
