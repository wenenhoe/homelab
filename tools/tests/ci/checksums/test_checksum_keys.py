"""The keys committed for the signed entries are the keys the registry names.

A key file is the trust anchor for its entry: the check accepts a signature only
from the one fingerprint the entry holds, so the file must hold that key and
nothing else. Changing either is a reviewed diff, and this fails until the two
agree again.

Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from ci.checksums.registry import ENTRIES, Signed

REPO_ROOT = Path(__file__).resolve().parents[4]
SIGNED = [entry for entry in ENTRIES if isinstance(entry, Signed)]


def primary_fingerprints(key: Path, home: Path) -> list[str]:
    listing = subprocess.run(
        ["gpg", "--homedir", str(home), "--batch", "--show-keys", "--with-colons", str(key)], capture_output=True, text=True, check=True
    ).stdout
    fingerprints: list[str] = []
    in_primary = False
    for line in listing.splitlines():
        fields = line.split(":")
        if fields[0] == "pub":
            in_primary = True
        elif fields[0] == "sub":
            in_primary = False
        elif fields[0] == "fpr" and in_primary:
            fingerprints.append(fields[9])
            in_primary = False
    return fingerprints


@pytest.fixture
def home(tmp_path_factory: pytest.TempPathFactory):
    path = tmp_path_factory.mktemp("g")
    path.chmod(0o700)
    yield path
    subprocess.run(["gpgconf", "--homedir", str(path), "--kill", "all"], capture_output=True, check=False)


@pytest.mark.parametrize("entry", SIGNED, ids=lambda entry: entry.name)
class TestCommittedKeys:
    def test_the_key_file_is_committed(self, entry):
        assert (REPO_ROOT / entry.key).is_file()

    def test_the_key_file_holds_the_entrys_fingerprint_and_no_other_key(self, entry, home):
        assert primary_fingerprints(REPO_ROOT / entry.key, home) == [entry.fingerprint]

    def test_the_key_file_is_a_public_key(self, entry):
        text = (REPO_ROOT / entry.key).read_text()
        assert text.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----")
        assert "PRIVATE" not in text
