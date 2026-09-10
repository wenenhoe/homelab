"""Unit tests for restore_all.py's discovery/orchestration logic.

Run via `uv run pytest ansible/tests/ -v`. Scoped to what's mockable
without real rclone/gpg/ansible-playbook — see docs/fire-drill.md for
the parts (real SeaweedFS/cloud reachability, real GPG decryption,
the actual restore role) that only a live fire drill can validate
honestly.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import restore_all


def _entry(app: str = "wastebin", host: str = "services", cloud_targets=None) -> restore_all.AppManifestEntry:
    return restore_all.AppManifestEntry(
        app=app,
        host=host,
        seaweedfs_path=app,
        volumes=[f"{app}_data"],
        cloud_targets=cloud_targets if cloud_targets is not None else [{"name": "b2", "bucket": "backups-b2"}],
    )


def _result(app: str = "wastebin", host: str = "services") -> restore_all.DiscoveryResult:
    return restore_all.DiscoveryResult(
        entry=_entry(app, host),
        source="seaweedfs",
        object_name=f"{host}-{app}-2026-09-01T12-00-00.tar.gz.gpg",
        backup_timestamp=datetime(2026, 9, 1, 12, tzinfo=UTC),
        decrypted_path=Path(f"/nonexistent/{app}.tar.gz"),
    )


class PickLatestTests(unittest.TestCase):
    def test_picks_the_newest_of_several_matching_objects(self):
        objects = [
            {"Name": "services-wastebin-2026-09-01T12-00-00.tar.gz.gpg"},
            {"Name": "services-wastebin-2026-09-03T12-00-00.tar.gz.gpg"},
            {"Name": "services-wastebin-2026-09-02T12-00-00.tar.gz.gpg"},
        ]
        name, timestamp = restore_all.pick_latest(objects, "services", "wastebin")
        self.assertEqual(name, "services-wastebin-2026-09-03T12-00-00.tar.gz.gpg")
        self.assertEqual(timestamp, datetime(2026, 9, 3, 12, tzinfo=UTC))

    def test_ignores_objects_for_a_different_app_or_host(self):
        objects = [
            {"Name": "services-tinyauth-2026-09-01T12-00-00.tar.gz.gpg"},
            {"Name": "play-wastebin-2026-09-01T12-00-00.tar.gz.gpg"},
        ]
        self.assertIsNone(restore_all.pick_latest(objects, "services", "wastebin"))

    def test_ignores_a_name_missing_the_trailing_dot_after_the_timestamp(self):
        # Guards the pattern's own r"\." anchor - a name that merely starts
        # with the right prefix but has no extension after the timestamp
        # should not match.
        objects = [{"Name": "services-wastebin-2026-09-01T12-00-00"}]
        self.assertIsNone(restore_all.pick_latest(objects, "services", "wastebin"))

    def test_returns_none_for_an_empty_object_list(self):
        self.assertIsNone(restore_all.pick_latest([], "services", "wastebin"))


class DiscoverAndDecryptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patch.object(restore_all, "SCRATCH_DIR", self.tmp).start()
        self.addCleanup(patch.stopall)

    def _good_copy_and_decrypt(self):
        """Patches the copyto + gpg steps to both succeed, for tests
        that only care about the discovery/fallback branch above them."""
        patch.object(restore_all, "_run_rclone", return_value=Mock(returncode=0, stderr="")).start()
        patch.object(restore_all.subprocess, "run", return_value=Mock(returncode=0, stderr="")).start()

    def test_uses_seaweedfs_when_it_has_a_matching_object(self):
        self._good_copy_and_decrypt()
        objects = [{"Name": "services-wastebin-2026-09-01T12-00-00.tar.gz.gpg"}]
        with patch.object(restore_all, "rclone_lsjson", return_value=objects):
            result = restore_all.discover_and_decrypt(_entry(), "the-bucket")

        self.assertEqual(result.source, "seaweedfs")
        self.assertEqual(result.object_name, "services-wastebin-2026-09-01T12-00-00.tar.gz.gpg")

    def test_falls_back_to_a_cloud_target_when_seaweedfs_is_unreachable(self):
        self._good_copy_and_decrypt()
        entry = _entry(cloud_targets=[{"name": "b2", "bucket": "backups-b2"}, {"name": "oci", "bucket": "backups-oci"}])
        objects = [{"Name": "services-wastebin-2026-09-01T12-00-00.tar.gz.gpg"}]

        def fake_lsjson(remote, bucket, prefix):
            if remote == "seaweedfs":
                return None  # unreachable
            if remote == "b2":
                return []  # reachable, but nothing there yet
            return objects  # oci has it

        with patch.object(restore_all, "rclone_lsjson", side_effect=fake_lsjson):
            result = restore_all.discover_and_decrypt(entry, "the-bucket")

        self.assertEqual(result.source, "oci")

    def test_raises_when_seaweedfs_and_every_cloud_target_are_unreachable(self):
        with patch.object(restore_all, "rclone_lsjson", return_value=None), self.assertRaisesRegex(restore_all.RestoreAllError, "unreachable"):
            restore_all.discover_and_decrypt(_entry(), "the-bucket")

    def test_raises_when_the_reachable_source_has_no_objects(self):
        with patch.object(restore_all, "rclone_lsjson", return_value=[]), self.assertRaisesRegex(restore_all.RestoreAllError, "no objects found"):
            restore_all.discover_and_decrypt(_entry(), "the-bucket")

    def test_raises_when_no_object_matches_the_expected_filename_pattern(self):
        objects = [{"Name": "not-a-matching-name.tar.gz.gpg"}]
        with patch.object(restore_all, "rclone_lsjson", return_value=objects), self.assertRaisesRegex(restore_all.RestoreAllError, "expected"):
            restore_all.discover_and_decrypt(_entry(), "the-bucket")

    def test_refuses_a_latest_object_without_a_gpg_suffix(self):
        # Security-relevant: every real backup_agent archive is
        # GPG-encrypted, so an unexpected non-.gpg name must not be
        # handed to gpg --decrypt as-is.
        objects = [{"Name": "services-wastebin-2026-09-01T12-00-00.tar.gz"}]
        with patch.object(restore_all, "rclone_lsjson", return_value=objects), self.assertRaisesRegex(restore_all.RestoreAllError, "no \\.gpg suffix"):
            restore_all.discover_and_decrypt(_entry(), "the-bucket")

    def test_raises_when_rclone_copyto_fails(self):
        objects = [{"Name": "services-wastebin-2026-09-01T12-00-00.tar.gz.gpg"}]
        with (
            patch.object(restore_all, "rclone_lsjson", return_value=objects),
            patch.object(restore_all, "_run_rclone", return_value=Mock(returncode=1, stderr="connection refused")),
            self.assertRaisesRegex(restore_all.RestoreAllError, "copyto from seaweedfs failed"),
        ):
            restore_all.discover_and_decrypt(_entry(), "the-bucket")

    def test_raises_when_gpg_decrypt_fails(self):
        objects = [{"Name": "services-wastebin-2026-09-01T12-00-00.tar.gz.gpg"}]
        with (
            patch.object(restore_all, "rclone_lsjson", return_value=objects),
            patch.object(restore_all, "_run_rclone", return_value=Mock(returncode=0, stderr="")),
            patch.object(restore_all.subprocess, "run", return_value=Mock(returncode=1, stderr="decryption failed: No secret key")),
            self.assertRaisesRegex(restore_all.RestoreAllError, "gpg --decrypt failed"),
        ):
            restore_all.discover_and_decrypt(_entry(), "the-bucket")


class MainBatchOrderingTests(unittest.TestCase):
    """The step-ca-first, step-ca-gates-everything-else contract from
    this module's own docstring - the part of main() that's safety-
    relevant rather than plumbing, so worth locking in independent of
    a live fire drill."""

    def setUp(self):
        patch.object(restore_all, "run_discovery_setup").start()
        patch.object(restore_all, "append_audit_log").start()
        patch.object(sys, "argv", ["restore_all.py", "--yes"]).start()
        self.addCleanup(patch.stopall)

    def _run_with(self, entries, discover_side_effect, restore_results):
        """entries: list[AppManifestEntry]. discover_side_effect: dict
        app -> DiscoveryResult, or app -> RestoreAllError instance to
        raise. restore_results: dict app -> bool for run_app_restore."""
        patch.object(restore_all, "load_manifest", return_value=("the-bucket", entries)).start()

        def fake_discover(entry, bucket):
            outcome = discover_side_effect[entry.app]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        patch.object(restore_all, "discover_and_decrypt", side_effect=fake_discover).start()
        mock_restore = patch.object(restore_all, "run_app_restore", side_effect=lambda r: restore_results[r.entry.app]).start()
        mock_minecraft = patch.object(restore_all, "run_minecraft_world_restore", return_value=True).start()
        return restore_all.main(), mock_restore, mock_minecraft

    def test_aborts_before_restoring_anything_if_step_ca_discovery_fails(self):
        entries = [_entry("step-ca"), _entry("wastebin")]
        rc, mock_restore, _ = self._run_with(
            entries,
            discover_side_effect={"step-ca": restore_all.RestoreAllError("boom"), "wastebin": _result("wastebin")},
            restore_results={},
        )
        self.assertEqual(rc, 1)
        mock_restore.assert_not_called()

    def test_aborts_the_rest_of_the_batch_if_step_ca_restore_fails(self):
        entries = [_entry("step-ca"), _entry("wastebin")]
        rc, mock_restore, _ = self._run_with(
            entries,
            discover_side_effect={"step-ca": _result("step-ca"), "wastebin": _result("wastebin")},
            restore_results={"step-ca": False, "wastebin": True},
        )
        self.assertEqual(rc, 1)
        mock_restore.assert_called_once()

    def test_a_failed_app_does_not_block_the_rest_of_the_batch(self):
        entries = [_entry("step-ca"), _entry("appA"), _entry("appB")]
        rc, mock_restore, _ = self._run_with(
            entries,
            discover_side_effect={"step-ca": _result("step-ca"), "appA": _result("appA"), "appB": _result("appB")},
            restore_results={"step-ca": True, "appA": False, "appB": True},
        )
        self.assertEqual(rc, 1)  # overall_ok is False because appA failed
        self.assertEqual(mock_restore.call_count, 3)  # appB still ran despite appA's failure

    def test_declining_the_confirmation_prompt_restores_nothing(self):
        patch.object(sys, "argv", ["restore_all.py"]).start()  # no --yes
        entries = [_entry("step-ca")]
        with patch("builtins.input", return_value="no"):
            rc, mock_restore, _ = self._run_with(
                entries,
                discover_side_effect={"step-ca": _result("step-ca")},
                restore_results={"step-ca": True},
            )
        self.assertEqual(rc, 1)
        mock_restore.assert_not_called()

    def test_minecraft_world_restore_runs_only_after_a_successful_minecraft_app_restore(self):
        entries = [_entry("step-ca"), _entry("minecraft")]
        rc, _mock_restore, mock_minecraft = self._run_with(
            entries,
            discover_side_effect={"step-ca": _result("step-ca"), "minecraft": _result("minecraft")},
            restore_results={"step-ca": True, "minecraft": True},
        )
        self.assertEqual(rc, 0)
        mock_minecraft.assert_called_once()

    def test_minecraft_world_restore_is_skipped_if_the_minecraft_app_restore_fails(self):
        entries = [_entry("step-ca"), _entry("minecraft")]
        rc, _mock_restore, mock_minecraft = self._run_with(
            entries,
            discover_side_effect={"step-ca": _result("step-ca"), "minecraft": _result("minecraft")},
            restore_results={"step-ca": True, "minecraft": False},
        )
        self.assertEqual(rc, 1)
        mock_minecraft.assert_not_called()


if __name__ == "__main__":
    unittest.main()
