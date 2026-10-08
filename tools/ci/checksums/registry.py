"""The registry of pinned release artifacts, and how far each one can be checked.

One entry per checksum pin in the repository. An entry says where the pin and
its version live, and carries what its tier needs
(docs/decisions/0077-knowing-a-pinned-release-checksum-is-the-publishers/revision-000.md):

- Signed: the publisher signs a manifest. The manifest and signature are
  fetched and verified against the key committed under keys/, and the pinned
  hash must equal the manifest's line for the file.
- Attested: the publisher publishes a build attestation for the file. The file
  is downloaded, must hash to the pin, and must pass `gh attestation verify`
  for the repository that builds it.
- Listed: the publisher lists a hash and signs nothing. The pinned hash must
  equal the listed one, which catches a hash copied from the wrong place and
  a typo, and no more.
- Unchecked: the publisher gives no way to check. The entry says so.

A new pinned artifact needs an entry here, which a test asserts.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar


class Tier(Enum):
    SIGNED = "signed"
    ATTESTED = "attested"
    LISTED = "listed"
    NONE = "none"


@dataclass(frozen=True)
class Location:
    """A value in a repository file: a top-level YAML key, or an `ARG` in a Dockerfile."""

    path: str
    name: str


_FINGERPRINT = re.compile(r"[0-9A-F]{40}")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def _template(entry: str, field: str, value: str, *, url: bool = True) -> None:
    names = {name for _, name, _, _ in string.Formatter().parse(value) if name is not None}
    if not names <= {"version"}:
        raise ValueError(f"{entry}: {field} may only use {{version}}")
    if url and not value.startswith("https://"):
        raise ValueError(f"{entry}: {field} must be an https URL")


@dataclass(frozen=True, kw_only=True)
class _Pinned:
    name: str
    pin: Location
    version: Location
    tier: ClassVar[Tier]


@dataclass(frozen=True, kw_only=True)
class Signed(_Pinned):
    tier: ClassVar[Tier] = Tier.SIGNED
    # The artifact's name as the manifest lists it, without a leading `./`. `{version}` is the pinned version here and in the URLs.
    file: str
    manifest_url: str
    # Absent when the manifest is clearsigned in place.
    signature_url: str | None = None
    # The signing key's primary fingerprint, upper case, and the committed file that must hold exactly that key.
    fingerprint: str
    key: str

    def __post_init__(self) -> None:
        _template(self.name, "file", self.file, url=False)
        _template(self.name, "manifest_url", self.manifest_url)
        if self.signature_url is not None:
            _template(self.name, "signature_url", self.signature_url)
        if not _FINGERPRINT.fullmatch(self.fingerprint):
            raise ValueError(f"{self.name}: fingerprint must be 40 upper-case hex digits")
        _bare_name(self.name, self.file)


@dataclass(frozen=True, kw_only=True)
class Attested(_Pinned):
    tier: ClassVar[Tier] = Tier.ATTESTED
    artifact_url: str
    # `owner/name` of the repository whose workflow must have built the artifact.
    repository: str

    def __post_init__(self) -> None:
        _template(self.name, "artifact_url", self.artifact_url)
        if not _REPOSITORY.fullmatch(self.repository):
            raise ValueError(f"{self.name}: repository must be owner/name")


@dataclass(frozen=True, kw_only=True)
class Listed(_Pinned):
    tier: ClassVar[Tier] = Tier.LISTED
    file: str
    manifest_url: str

    def __post_init__(self) -> None:
        _template(self.name, "file", self.file, url=False)
        _template(self.name, "manifest_url", self.manifest_url)
        _bare_name(self.name, self.file)


@dataclass(frozen=True, kw_only=True)
class Unchecked(_Pinned):
    tier: ClassVar[Tier] = Tier.NONE
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(f"{self.name}: say why there is nothing to check this pin against")


def _bare_name(entry: str, file: str) -> None:
    if not file or file.startswith(("./", "/")) or any(c.isspace() for c in file):
        raise ValueError(f"{entry}: file must be a bare name")


Entry = Signed | Attested | Listed | Unchecked

_CD_AGENT = "ansible/roles/cd_agent/defaults/main.yaml"
_OPENBAO_CLI = "ansible/roles/openbao_cli/defaults/main.yaml"
_CODERABBIT = "tools/coderabbit-review/Dockerfile"
KEYS = "tools/ci/checksums/keys"

ENTRIES: tuple[Entry, ...] = (
    Attested(
        name="uv",
        pin=Location(_CD_AGENT, "cd_agent_uv_sha256"),
        version=Location(_CD_AGENT, "cd_agent_uv_version"),
        artifact_url="https://github.com/astral-sh/uv/releases/download/{version}/uv-x86_64-unknown-linux-gnu.tar.gz",
        repository="astral-sh/uv",
    ),
    Signed(
        name="rclone",
        pin=Location(_CD_AGENT, "cd_agent_rclone_sha256"),
        version=Location(_CD_AGENT, "cd_agent_rclone_version"),
        file="rclone-v{version}-linux-amd64.zip",
        manifest_url="https://downloads.rclone.org/v{version}/SHA256SUMS",
        fingerprint="FBF737ECE9F8AB18604BD2AC93935E02FF3B54FA",
        key=f"{KEYS}/rclone.asc",
    ),
    Signed(
        name="openbao-cli",
        pin=Location(_OPENBAO_CLI, "openbao_cli_deb_sha256"),
        version=Location(_OPENBAO_CLI, "openbao_cli_version"),
        file="openbao_{version}_linux_amd64.deb",
        manifest_url="https://github.com/openbao/openbao/releases/download/v{version}/checksums.txt",
        signature_url="https://github.com/openbao/openbao/releases/download/v{version}/checksums.txt.gpgsig",
        fingerprint="66D15FDD87287219C8E15478D200CD702853E6D0",
        key=f"{KEYS}/openbao.asc",
    ),
    Listed(
        name="coderabbit-cli",
        pin=Location(_CODERABBIT, "CODERABBIT_SHA256"),
        version=Location(_CODERABBIT, "CODERABBIT_VERSION"),
        file="coderabbit-linux-x64.zip",
        manifest_url="https://cli.coderabbit.ai/releases/{version}/SHA256SUMS",
    ),
)
