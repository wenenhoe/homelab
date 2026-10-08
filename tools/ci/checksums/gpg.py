"""Verifying a signed manifest with gpg, in a keyring that holds only the committed key.

No key is ever fetched: the keyring is built from the one file the repository
commits for the entry, and gpg runs with its network helper disabled, so a
signature by any other key finds no key to verify against and fails.
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
from pathlib import Path

from ci import proc

# Any of these in gpg's status output means the signature is not good, whatever else it printed.
_REJECTED = frozenset({"BADSIG", "ERRSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG", "NO_PUBKEY", "NODATA", "KEYEXPIRED", "FAILURE"})
_OFFLINE = ["--batch", "--no-tty", "--disable-dirmngr", "--no-auto-key-retrieve", "--no-auto-key-locate"]


class SignatureError(Exception):
    """The manifest is not shown to be signed by the committed key."""


def _statuses(stdout: str) -> list[tuple[str, list[str]]]:
    """gpg's `--status-fd` lines, as (keyword, arguments)."""
    parsed = []
    for line in stdout.splitlines():
        if line.startswith("[GNUPG:] "):
            keyword, *arguments = line.removeprefix("[GNUPG:] ").split()
            parsed.append((keyword, arguments))
    return parsed


def _gpg(run: proc.Runner, home: Path, *args: str):
    try:
        return run(["gpg", "--homedir", str(home), *_OFFLINE, "--status-fd", "1", *args], home, True)
    except FileNotFoundError as exc:
        raise SignatureError("gpg is not installed") from exc


def _primary_fingerprints(run: proc.Runner, home: Path) -> set[str]:
    listing = _gpg(run, home, "--list-keys", "--with-colons")
    if listing.returncode != 0:
        raise SignatureError("gpg can't list the keyring built from the committed key")
    fingerprints: set[str] = set()
    in_primary = False
    for line in listing.stdout.splitlines():
        fields = line.split(":")
        if fields[0] == "pub":
            in_primary = True
        elif fields[0] == "sub":
            in_primary = False
        elif fields[0] == "fpr" and in_primary:
            fingerprints.add(fields[9].upper())
            in_primary = False
    return fingerprints


def verify_manifest(key: Path, fingerprint: str, manifest: bytes, signature: bytes | None, run: proc.Runner = proc.run) -> str:
    """The signed manifest text, when `signature` (or the manifest, when it is clearsigned) is by `fingerprint`'s key.

    `signature` is None for a clearsigned manifest. The text returned for one
    is what gpg reports as signed, not the file as fetched: text placed around
    the signed block is not covered by the signature.
    """
    # The keyring is only a directory of files; gpg also starts an agent for it that must be stopped before it goes.
    home = Path(tempfile.mkdtemp(prefix="gpg-"))
    try:
        return _verify(home, key, fingerprint.upper(), manifest, signature, run)
    finally:
        with contextlib.suppress(FileNotFoundError):
            run(["gpgconf", "--homedir", str(home), "--kill", "all"], home, True)
        shutil.rmtree(home, ignore_errors=True)


def _verify(home: Path, key: Path, fingerprint: str, manifest: bytes, signature: bytes | None, run: proc.Runner) -> str:
    if not key.is_file():
        raise SignatureError(f"the key file {key.name} is not committed")
    imported = _gpg(run, home, "--import", str(key))
    if imported.returncode != 0 or not any(keyword == "IMPORT_OK" for keyword, _ in _statuses(imported.stdout)):
        raise SignatureError(f"gpg can't import {key.name}")
    # With only this key in the keyring, a signature that verifies is by it or by one of its subkeys.
    held = _primary_fingerprints(run, home)
    if held != {fingerprint}:
        raise SignatureError(f"{key.name} holds {', '.join(sorted(held)) or 'no key'}, not only {fingerprint}")

    signed = home / "manifest"
    signed.write_bytes(manifest)
    if signature is None:
        text_out = home / "signed-text"
        result = _gpg(run, home, "--output", str(text_out), "--decrypt", str(signed))
    else:
        text_out = signed
        sig = home / "manifest.sig"
        sig.write_bytes(signature)
        result = _gpg(run, home, "--verify", str(sig), str(signed))

    statuses = _statuses(result.stdout)
    rejected = sorted({keyword for keyword, _ in statuses if keyword in _REJECTED})
    if rejected:
        raise SignatureError(f"gpg reports {', '.join(rejected)}")
    if result.returncode != 0 or not any(keyword == "VALIDSIG" for keyword, _ in statuses):
        raise SignatureError("the manifest carries no valid signature")
    # gpg writes the text out even when it rejects the signature, so this is read only once every check above has passed.
    try:
        return text_out.read_text()
    except UnicodeDecodeError as exc:
        raise SignatureError("the signed manifest is not text") from exc
