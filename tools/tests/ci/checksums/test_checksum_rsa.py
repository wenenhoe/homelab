"""Tests for ci.checksums.rsa, against real openssl and RSA keys generated per test.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest
from ci import proc
from ci.checksums import rsa
from ci.checksums.gpg import SignatureError

MANIFEST = b"SHA256 (tool.img.bz2) = " + b"a" * 64 + b"\n"


@pytest.fixture
def key(tmp_path, rsa_signer) -> Path:
    path = tmp_path / "tool.pem"
    path.write_text(rsa_signer.pem)
    return path


class TestKeyFingerprint:
    def test_it_is_the_sha256_of_the_keys_der_as_openssl_prints_it(self, key, rsa_signer):
        der = subprocess.run(["openssl", "pkey", "-pubin", "-in", str(key), "-outform", "DER"], check=True, capture_output=True).stdout
        digest = subprocess.run(["sha256sum"], input=der, check=True, capture_output=True).stdout.split()[0].decode()
        assert rsa.key_fingerprint(key) == digest == rsa_signer.fingerprint

    def test_a_file_holding_exactly_one_key_is_accepted(self, key):
        assert len(rsa.key_fingerprint(key)) == 64

    def test_a_second_key_in_the_file_is_refused(self, key, make_rsa_signer):
        key.write_text(key.read_text() + make_rsa_signer("other").pem)
        with pytest.raises(SignatureError, match="exactly one PEM public key"):
            rsa.key_fingerprint(key)

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("", id="empty"),
            pytest.param("not a key\n", id="not-pem"),
            pytest.param("-----BEGIN PUBLIC KEY-----\n!!!!\n-----END PUBLIC KEY-----\n", id="not-base64"),
            pytest.param("-----BEGIN PUBLIC KEY-----\nQUJD\n-----END PUBLIC KEY-----\ntrailing text\n", id="trailing-text"),
            pytest.param("# note\n-----BEGIN PUBLIC KEY-----\nQUJD\n-----END PUBLIC KEY-----\n", id="leading-text"),
            pytest.param("-----BEGIN PRIVATE KEY-----\nQUJD\n-----END PRIVATE KEY-----\n", id="private-key"),
        ],
    )
    def test_anything_that_is_not_one_public_key_is_refused(self, tmp_path, text):
        path = tmp_path / "bad.pem"
        path.write_text(text)
        with pytest.raises(SignatureError):
            rsa.key_fingerprint(path)

    def test_a_missing_file_is_refused(self, tmp_path):
        with pytest.raises(SignatureError, match="can't be read"):
            rsa.key_fingerprint(tmp_path / "absent.pem")


class TestVerifyManifest:
    def test_a_manifest_signed_by_the_committed_key_is_returned_as_text(self, key, rsa_signer):
        assert rsa.verify_manifest(key, rsa_signer.fingerprint, MANIFEST, rsa_signer.sign(MANIFEST)) == MANIFEST.decode()

    def test_a_signature_on_one_line_without_a_trailing_newline_is_accepted(self, key, rsa_signer):
        one_line = rsa_signer.sign(MANIFEST).replace(b"\n", b"")
        assert rsa.verify_manifest(key, rsa_signer.fingerprint, MANIFEST, one_line)

    def test_a_manifest_altered_after_signing_fails(self, key, rsa_signer):
        with pytest.raises(SignatureError, match="no valid signature"):
            rsa.verify_manifest(key, rsa_signer.fingerprint, MANIFEST.replace(b"a", b"b"), rsa_signer.sign(MANIFEST))

    def test_a_signature_by_another_key_fails(self, key, rsa_signer, make_rsa_signer):
        with pytest.raises(SignatureError, match="no valid signature"):
            rsa.verify_manifest(key, rsa_signer.fingerprint, MANIFEST, make_rsa_signer("other").sign(MANIFEST))

    def test_a_key_file_that_holds_another_key_than_the_entrys_fails_before_anything_is_verified(self, key, make_rsa_signer):
        other = make_rsa_signer("other")
        calls: list[list[str]] = []

        def run(args, cwd, capture):
            calls.append(args)
            raise AssertionError("openssl must not run")

        with pytest.raises(SignatureError, match="not " + other.fingerprint):
            rsa.verify_manifest(key, other.fingerprint, MANIFEST, other.sign(MANIFEST), run)
        assert calls == []

    @pytest.mark.parametrize(
        ("signature", "message"),
        [
            pytest.param(b"", "plausible size", id="empty"),
            pytest.param(b"\n\n", "plausible size", id="blank"),
            pytest.param(b"not base64 !!", "not base64", id="not-base64"),
            pytest.param(base64.b64encode(b"x" * (rsa.SIGNATURE_LIMIT + 1)), "plausible size", id="too-large"),
            pytest.param(base64.b64encode(b"not a signature"), "no valid signature", id="garbage"),
        ],
    )
    def test_a_signature_that_is_not_one_fails(self, key, rsa_signer, signature, message):
        with pytest.raises(SignatureError, match=message):
            rsa.verify_manifest(key, rsa_signer.fingerprint, MANIFEST, signature)

    def test_openssl_must_say_verified_ok_whatever_its_exit_status(self, key, rsa_signer):
        def run(args, cwd, capture):
            return subprocess.CompletedProcess(args, 0, stdout="Verification Failure\n", stderr="")

        with pytest.raises(SignatureError, match="no valid signature"):
            rsa.verify_manifest(key, rsa_signer.fingerprint, MANIFEST, rsa_signer.sign(MANIFEST), run)

    def test_a_clean_exit_with_no_verdict_is_not_a_pass(self, key, rsa_signer):
        def run(args, cwd, capture):
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with pytest.raises(SignatureError):
            rsa.verify_manifest(key, rsa_signer.fingerprint, MANIFEST, rsa_signer.sign(MANIFEST), run)

    def test_a_missing_openssl_is_said_so(self, key, rsa_signer):
        def run(args, cwd, capture):
            raise FileNotFoundError(args[0])

        with pytest.raises(SignatureError, match="openssl is not installed"):
            rsa.verify_manifest(key, rsa_signer.fingerprint, MANIFEST, rsa_signer.sign(MANIFEST), run)

    def test_openssl_is_asked_to_verify_with_the_committed_key_only(self, key, rsa_signer):
        seen: list[list[str]] = []

        def run(args, cwd, capture):
            seen.append(args)
            return proc.run(args, cwd, capture)

        rsa.verify_manifest(key, rsa_signer.fingerprint, MANIFEST, rsa_signer.sign(MANIFEST), run)
        assert [(a[:4], a[4]) for a in seen] == [(["openssl", "dgst", "-sha256", "-verify"], str(key.resolve()))]

    def test_a_manifest_that_is_not_text_is_refused(self, key, rsa_signer):
        binary = b"\xff\xfe\x00"
        with pytest.raises(SignatureError, match="not text"):
            rsa.verify_manifest(key, rsa_signer.fingerprint, binary, rsa_signer.sign(binary))
