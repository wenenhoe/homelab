"""Verifying a manifest signed with an RSA key, against the one key the repository commits for it.

Some publishers (OPNsense) sign their checksum file with OpenSSL: the signature
file is the base64 of an RSA PKCS#1 v1.5 signature over the SHA-256 of the
checksum file, and the public key is a PEM file. No key is ever fetched: the
key is the file the repository commits for the entry, and it must be exactly
one public key whose SHA-256 of its DER encoding (what
`openssl pkey -pubin -outform DER | sha256sum` prints) is the entry's
fingerprint, so a signature by any other key fails.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import tempfile
from pathlib import Path

from ci import proc
from ci.checksums.gpg import SignatureError

SIGNATURE_LIMIT = 8192
_KEY = re.compile(r"-----BEGIN PUBLIC KEY-----\n(?P<body>[A-Za-z0-9+/=\n]+)\n-----END PUBLIC KEY-----\n?")


def key_fingerprint(key: Path) -> str:
    """The SHA-256 of the DER encoding of the one public key `key` holds, lower case.

    A file with anything else in it, a second key included, is refused: the
    file is the trust anchor, and what is not the key has no place in it.
    """
    try:
        text = key.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        raise SignatureError(f"the key file {key.name} can't be read: {exc}") from exc
    match = _KEY.fullmatch(text)
    if not match:
        raise SignatureError(f"{key.name} is not exactly one PEM public key")
    try:
        der = base64.b64decode(match.group("body").replace("\n", ""), validate=True)
    except binascii.Error as exc:
        raise SignatureError(f"{key.name} is not valid base64") from exc
    return hashlib.sha256(der).hexdigest()


def _decode(signature: bytes) -> bytes:
    try:
        raw = base64.b64decode(b"".join(signature.split()), validate=True)
    except binascii.Error as exc:
        raise SignatureError("the signature file is not base64") from exc
    if not raw or len(raw) > SIGNATURE_LIMIT:
        raise SignatureError("the signature file holds no signature of a plausible size")
    return raw


def verify_manifest(key: Path, fingerprint: str, manifest: bytes, signature: bytes, run: proc.Runner = proc.run) -> str:
    """The manifest text, when `signature` over it is by the key `fingerprint` names and `key` holds."""
    held = key_fingerprint(key)
    if held != fingerprint:
        raise SignatureError(f"{key.name} holds {held}, not {fingerprint}")
    raw = _decode(signature)
    with tempfile.TemporaryDirectory(prefix="rsa-") as directory:
        work = Path(directory)
        (work / "manifest").write_bytes(manifest)
        (work / "manifest.sig").write_bytes(raw)
        try:
            result = run(["openssl", "dgst", "-sha256", "-verify", str(key.resolve()), "-signature", "manifest.sig", "manifest"], work, True)
        except FileNotFoundError as exc:
            raise SignatureError("openssl is not installed") from exc
    if result.returncode != 0 or result.stdout.strip() != "Verified OK":
        raise SignatureError("the manifest carries no valid signature by the committed key")
    try:
        return manifest.decode()
    except UnicodeDecodeError as exc:
        raise SignatureError("the signed manifest is not text") from exc
