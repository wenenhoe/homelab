"""Tests for ci.checksums.gpg, against real gpg and generated keys.

Nothing here reaches a publisher. A key is generated for each test, and the
manifests are signed with it, so the signature cases are real gpg verdicts
and not canned status lines.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import re
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from ci import proc
from ci.checksums import gpg

MANIFEST = "aaaa  one.zip\nbbbb  ./two.zip\n"


class Recording:
    """A runner that runs the real command, optionally rewritten first, and keeps every argv it was given."""

    def __init__(self, rewrite: Callable[[list[str]], list[str]] = list) -> None:
        self.rewrite = rewrite
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        return proc.run(self.rewrite(args), cwd, capture)

    @property
    def gpg_calls(self) -> list[list[str]]:
        return [call for call in self.calls if call[0] == "gpg"]


@pytest.fixture
def key(root: Path, signer) -> Path:
    path = root / "publisher.asc"
    path.write_bytes(signer.public_key())
    return path


class TestClearsigned:
    def test_a_manifest_signed_by_the_committed_key_comes_back_as_signed(self, signer, key):
        assert gpg.verify_manifest(key, signer.fingerprint, signer.clearsign(MANIFEST), None) == MANIFEST

    def test_text_placed_around_the_signed_block_is_not_part_of_what_comes_back(self, signer, key):
        manifest = b"cccc  evil.zip\n" + signer.clearsign(MANIFEST) + b"dddd  evil.zip\n"
        assert gpg.verify_manifest(key, signer.fingerprint, manifest, None) == MANIFEST

    def test_an_altered_signed_line_fails(self, signer, key):
        altered = signer.clearsign(MANIFEST).replace(b"aaaa  one.zip", b"cccc  one.zip")
        with pytest.raises(gpg.SignatureError, match="BADSIG"):
            gpg.verify_manifest(key, signer.fingerprint, altered, None)

    def test_a_manifest_with_no_signature_fails(self, signer, key):
        with pytest.raises(gpg.SignatureError, match="NODATA"):
            gpg.verify_manifest(key, signer.fingerprint, MANIFEST.encode(), None)

    def test_a_signature_by_another_key_fails(self, signer, make_signer, key):
        other = make_signer("Other")
        with pytest.raises(gpg.SignatureError, match="NO_PUBKEY"):
            gpg.verify_manifest(key, signer.fingerprint, other.clearsign(MANIFEST), None)

    def test_a_signature_by_a_key_that_has_since_expired_fails(self, make_signer, root):
        # gpg reports such a signature as both EXPKEYSIG and VALIDSIG, and exits 0.
        old = make_signer("Old", created="20200101T000000", expires="1d")
        expired = root / "old.asc"
        expired.write_bytes(old.public_key())
        manifest = old.clearsign(MANIFEST, at="20200101T120000")
        with pytest.raises(gpg.SignatureError, match="EXPKEYSIG"):
            gpg.verify_manifest(expired, old.fingerprint, manifest, None)


class TestDetached:
    def test_a_manifest_with_a_signature_by_the_committed_key_comes_back(self, signer, key):
        manifest = MANIFEST.encode()
        assert gpg.verify_manifest(key, signer.fingerprint, manifest, signer.detach(manifest)) == MANIFEST

    def test_a_manifest_changed_after_it_was_signed_fails(self, signer, key):
        signature = signer.detach(MANIFEST.encode())
        with pytest.raises(gpg.SignatureError, match="BADSIG"):
            gpg.verify_manifest(key, signer.fingerprint, MANIFEST.replace("aaaa", "cccc").encode(), signature)

    def test_a_signature_by_another_key_fails(self, signer, make_signer, key):
        manifest = MANIFEST.encode()
        with pytest.raises(gpg.SignatureError, match="NO_PUBKEY"):
            gpg.verify_manifest(key, signer.fingerprint, manifest, make_signer("Other").detach(manifest))

    def test_a_signature_that_is_not_one_fails(self, signer, key):
        with pytest.raises(gpg.SignatureError, match="NODATA"):
            gpg.verify_manifest(key, signer.fingerprint, MANIFEST.encode(), b"not a signature")


class TestKeyFile:
    def test_a_key_file_that_is_not_committed_fails(self, signer, root):
        with pytest.raises(gpg.SignatureError, match=re.escape("publisher.asc is not committed")):
            gpg.verify_manifest(root / "publisher.asc", signer.fingerprint, signer.clearsign(MANIFEST), None)

    def test_a_file_that_is_not_a_key_fails(self, signer, root):
        path = root / "publisher.asc"
        path.write_text("not a key\n")
        with pytest.raises(gpg.SignatureError, match=re.escape("can't import publisher.asc")):
            gpg.verify_manifest(path, signer.fingerprint, signer.clearsign(MANIFEST), None)

    def test_a_file_holding_a_different_key_than_the_fingerprint_names_fails(self, signer, make_signer, root):
        other = make_signer("Other")
        path = root / "publisher.asc"
        path.write_bytes(other.public_key())
        with pytest.raises(gpg.SignatureError, match=f"holds {other.fingerprint}, not only {signer.fingerprint}"):
            gpg.verify_manifest(path, signer.fingerprint, signer.clearsign(MANIFEST), None)

    def test_a_file_holding_the_right_key_and_another_fails(self, signer, make_signer, root):
        other = make_signer("Other")
        path = root / "publisher.asc"
        path.write_bytes(signer.public_key() + other.public_key())
        with pytest.raises(gpg.SignatureError, match="not only"):
            gpg.verify_manifest(path, signer.fingerprint, signer.clearsign(MANIFEST), None)

    def test_the_fingerprint_is_compared_without_regard_to_case(self, signer, key):
        assert gpg.verify_manifest(key, signer.fingerprint.lower(), signer.clearsign(MANIFEST), None) == MANIFEST


class TestKeyIsNeverFetched:
    """The keyring is the committed file and nothing else, even where gpg has been set up to look elsewhere."""

    @staticmethod
    def _stub_key_server(root: Path) -> tuple[Path, Path]:
        """A dirmngr that records that it was started, and the file it leaves."""
        marker = root / "dirmngr-was-started"
        stub = root / "dirmngr"
        stub.write_text(f"#!/bin/sh\ntouch {marker}\nexit 2\n")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        return stub, marker

    @staticmethod
    def _asking_for_keys(stub: Path, strip: tuple[str, ...] = ()) -> Callable[[list[str]], list[str]]:
        """Options as an enabling gpg.conf would apply them, ahead of the verifier's own, with `strip` removed from those."""

        def rewrite(args: list[str]) -> list[str]:
            if args[0] != "gpg":
                return args
            enable = ["--auto-key-retrieve", "--auto-key-locate", "keyserver", "--keyserver", "hkps://keys.example.invalid", "--dirmngr-program", str(stub)]
            return [args[0], *enable, *(arg for arg in args[1:] if arg not in strip)]

        return rewrite

    def test_the_harness_sees_gpg_reach_for_a_key_server_when_not_held_back(self, signer, make_signer, key, root):
        stub, marker = self._stub_key_server(root)
        run = Recording(self._asking_for_keys(stub, strip=("--disable-dirmngr", "--no-auto-key-retrieve", "--no-auto-key-locate")))
        with pytest.raises(gpg.SignatureError):
            gpg.verify_manifest(key, signer.fingerprint, make_signer("Other").clearsign(MANIFEST), None, run)
        assert marker.exists()

    def test_a_signature_by_an_unknown_key_starts_no_key_server_lookup(self, signer, make_signer, key, root):
        stub, marker = self._stub_key_server(root)
        run = Recording(self._asking_for_keys(stub))
        with pytest.raises(gpg.SignatureError, match="NO_PUBKEY"):
            gpg.verify_manifest(key, signer.fingerprint, make_signer("Other").clearsign(MANIFEST), None, run)
        assert not marker.exists()

    def test_every_gpg_call_switches_off_the_network_helper_and_key_retrieval(self, signer, key):
        run = Recording()
        gpg.verify_manifest(key, signer.fingerprint, signer.clearsign(MANIFEST), None, run)
        assert len(run.gpg_calls) == 3
        for call in run.gpg_calls:
            assert {"--disable-dirmngr", "--no-auto-key-retrieve", "--no-auto-key-locate"} <= set(call)


class TestKeyring:
    def test_the_keyring_is_removed_and_its_agent_stopped_after_a_good_verification(self, signer, key):
        run = Recording()
        gpg.verify_manifest(key, signer.fingerprint, signer.clearsign(MANIFEST), None, run)
        home = Path(run.calls[0][run.calls[0].index("--homedir") + 1])
        assert run.calls[-1] == ["gpgconf", "--homedir", str(home), "--kill", "all"]
        assert not home.exists()

    def test_and_after_a_failed_one(self, signer, make_signer, key):
        run = Recording()
        with pytest.raises(gpg.SignatureError):
            gpg.verify_manifest(key, signer.fingerprint, make_signer("Other").clearsign(MANIFEST), None, run)
        home = Path(run.calls[0][run.calls[0].index("--homedir") + 1])
        assert run.calls[-1] == ["gpgconf", "--homedir", str(home), "--kill", "all"]
        assert not home.exists()

    def test_every_call_runs_in_the_keyring_not_in_the_repository(self, signer, key):
        seen: list[Path] = []

        def run(args: list[str], cwd: Path, capture: bool = False):
            seen.append(cwd)
            return proc.run(args, cwd, capture)

        gpg.verify_manifest(key, signer.fingerprint, signer.clearsign(MANIFEST), None, run)
        assert len(set(seen)) == 1
        assert key.parent not in seen

    def test_a_missing_gpg_is_reported_as_such(self, key):
        def run(args: list[str], cwd: Path, capture: bool = False):
            raise FileNotFoundError(args[0])

        with pytest.raises(gpg.SignatureError, match="gpg is not installed"):
            gpg.verify_manifest(key, "A" * 40, b"", None, run)
