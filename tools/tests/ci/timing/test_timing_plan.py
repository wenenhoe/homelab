"""Tests for ci.timing.plan.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

from datetime import date

import pytest
from ci.timing import plan

TODAY = date(2026, 11, 15)


def entry(fingerprint="f", measured="2026-11-01"):
    return {"fingerprint": fingerprint, "measured": measured, "seconds": {"x": 1}}


class TestReason:
    def test_a_measurement_of_the_same_files_that_is_recent_holds(self):
        assert plan.reason(entry(), "f", TODAY, 90) is None

    def test_a_role_with_no_entry_is_not_measured(self):
        assert plan.reason(None, "f", TODAY, 90) == "not measured"

    def test_changed_files_name_themselves_as_the_reason(self):
        assert plan.reason(entry("old"), "new", TODAY, 90) == "its files changed"

    def test_a_measurement_past_the_age_limit_is_taken_again(self):
        assert plan.reason(entry(measured="2026-08-01"), "f", TODAY, 90) == "measured 106 days ago"

    def test_a_measurement_exactly_at_the_age_limit_still_holds(self):
        assert plan.reason(entry(measured="2026-08-17"), "f", TODAY, 90) is None

    @pytest.mark.parametrize("measured", ["yesterday", None, 5], ids=["not a date", "null", "number"])
    def test_a_measurement_without_a_valid_date_is_taken_again(self, measured):
        assert plan.reason(entry(measured=measured), "f", TODAY, 90) == "measurement has no valid date"

    def test_an_entry_that_is_not_an_object_counts_as_missing(self):
        assert plan.reason("garbage", "f", TODAY, 90) == "not measured"


class TestStaleRoles:
    def test_only_the_roles_that_need_timing_are_named_with_their_reason(self):
        recorded = {"version": 1, "roles": {"same": entry("a"), "moved": entry("b")}}
        current = {"same": "a", "moved": "c", "new": "d"}
        assert plan.stale_roles(recorded, current, TODAY, 90) == {"moved": "its files changed", "new": "not measured"}

    def test_force_names_every_current_role(self):
        recorded = {"version": 1, "roles": {"same": entry("a")}}
        assert plan.stale_roles(recorded, {"same": "a", "other": "b"}, TODAY, 90, force=True) == {"same": "forced", "other": "forced"}

    def test_a_recorded_role_that_no_longer_exists_is_not_named(self):
        assert plan.stale_roles({"version": 1, "roles": {"gone": entry()}}, {}, TODAY, 90) == {}


class TestMain:
    def test_it_writes_the_roles_to_time_as_a_json_array(self, root, monkeypatch, capsys):
        monkeypatch.setattr(plan.fingerprint, "fingerprints", lambda _root: {"a": "1", "b": "2"})
        plan.state.save(root / "s.json", {"version": 1, "roles": {"a": entry("1", date.today().isoformat())}})
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        assert plan.main(["--state", str(root / "s.json")]) == 0
        assert 'roles=["b"]' in capsys.readouterr().out

    def test_a_missing_state_file_times_every_role(self, root, monkeypatch, capsys):
        monkeypatch.setattr(plan.fingerprint, "fingerprints", lambda _root: {"a": "1", "b": "2"})
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        assert plan.main(["--state", str(root / "missing.json")]) == 0
        assert 'roles=["a","b"]' in capsys.readouterr().out

    def test_a_fingerprint_failure_fails_the_run_instead_of_timing_nothing(self, root, monkeypatch, capsys):
        def fail(_root):
            raise plan.fingerprint.FingerprintError("git ls-files exited 128")

        monkeypatch.setattr(plan.fingerprint, "fingerprints", fail)
        assert plan.main(["--state", str(root / "s.json")]) == 1
        assert "git ls-files exited 128" in capsys.readouterr().err
