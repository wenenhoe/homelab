"""Fixtures for the checksum tests: real OpenPGP keys, and a repository tree the registry can read."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

_BATCH = ["gpg", "--batch", "--no-tty", "--pinentry-mode", "loopback", "--passphrase", ""]


class Signer:
    """A generated OpenPGP signing key in a keyring of its own.

    Its home comes from `tmp_path_factory`, not `tmp_path`: gpg-agent's sockets
    live in the home and a long path stops the agent from starting.
    """

    def __init__(self, home: Path, name: str, created: str | None = None, expires: str = "never") -> None:
        self.home = home
        self.name = name
        self._faked = ["--faked-system-time", created] if created else []
        self._run("--quick-generate-key", f"{name} <{name.lower()}@example.invalid>", "ed25519", "sign", expires)

    def _run(self, *args: str, at: str | None = None, stdin: bytes | None = None) -> bytes:
        faked = ["--faked-system-time", at] if at else self._faked
        result = subprocess.run([*_BATCH, "--homedir", str(self.home), *faked, *args], input=stdin, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr.decode()
        return result.stdout

    @property
    def fingerprint(self) -> str:
        listing = subprocess.run(["gpg", "--homedir", str(self.home), "--list-keys", "--with-colons"], capture_output=True, text=True, check=True).stdout
        return next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))

    def public_key(self) -> bytes:
        return self._run("--armor", "--export")

    def clearsign(self, text: str, at: str | None = None) -> bytes:
        return self._run("--clearsign", stdin=text.encode(), at=at)

    def detach(self, data: bytes, at: str | None = None) -> bytes:
        return self._run("--detach-sign", stdin=data, at=at)

    def stop(self) -> None:
        subprocess.run(["gpgconf", "--homedir", str(self.home), "--kill", "all"], capture_output=True, check=False)


@pytest.fixture
def make_signer(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Callable[..., Signer]]:
    signers: list[Signer] = []

    def make(name: str = "Publisher", created: str | None = None, expires: str = "never") -> Signer:
        home = tmp_path_factory.mktemp("g")
        home.chmod(0o700)
        signer = Signer(home, name, created, expires)
        signers.append(signer)
        return signer

    yield make
    for signer in signers:
        signer.stop()


@pytest.fixture
def signer(make_signer: Callable[..., Signer]) -> Signer:
    return make_signer()
