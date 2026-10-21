"""The registry of pinned image repositories, and how far each one's digests can be checked.

One entry per image repository the tree pins. An entry fixes everything a
verifier is allowed to trust, and none of it is read from the registry or from
the image being checked
(docs/decisions/0084-knowing-a-pinned-image-digest-is-the-publishers/revision-000.md):

- Attested: the publisher's workflow attests the digests it pushes. Each pinned
  digest must pass `gh attestation verify` for the repository the entry names.
- Signed: the publisher signs the digests it pushes. Each pinned digest must
  pass `cosign verify` with the certificate identity and OIDC issuer the entry
  fixes, or, for a publisher that signs with a key, with the public key
  committed under keys/ for it.
- Unsigned: the publisher offers nothing the check can verify, and the entry
  says why. A BuildKit attestation or an SBOM that nothing ties to an identity
  the repository fixes does not lift an image out of this tier.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from ci.images.remote import parse_image


class Tier(Enum):
    ATTESTED = "attested"
    SIGNED = "signed"
    UNSIGNED = "unsigned"


KEYS = "tools/ci/provenance/keys"

_REPOSITORY = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_.-]*/[A-Za-z0-9_.][A-Za-z0-9_.-]*")
_KEY = re.compile(rf"{re.escape(KEYS)}/[a-z0-9][a-z0-9-]*\.pub")
# Both `cosign verify` and the library under it match a pattern anywhere in the certificate's identity unless it is anchored.
# It must also open on a literal host, so `^https://.*$` can't stand for an identity.
_ANCHORED_IDENTITY = re.compile(r"\^https://[A-Za-z0-9].*")


def _image(entry: str) -> None:
    remainder, at, _ = entry.partition("@")
    _, colon, tail = remainder.rpartition(":")
    if at or (colon and "/" not in tail):
        raise ValueError(f"{entry}: name the image repository without a tag or a digest")
    try:
        parse_image(entry)
    except ValueError as exc:
        raise ValueError(f"{entry}: {exc}") from exc


@dataclass(frozen=True, kw_only=True)
class _Entry:
    # The repository as a reference writes it, without tag or digest: `ghcr.io/owner/name`, or `owner/name` for Docker Hub.
    image: str
    tier: ClassVar[Tier]

    @property
    def registry_key(self) -> tuple[str, str]:
        """(registry host, repository) exactly as `ci.images.remote.parse_image` reads a reference to it."""
        parsed = parse_image(self.image)
        return parsed.registry, parsed.repository


@dataclass(frozen=True, kw_only=True)
class Attested(_Entry):
    tier: ClassVar[Tier] = Tier.ATTESTED
    # `owner/name` of the repository whose workflow must have attested the image.
    repository: str

    def __post_init__(self) -> None:
        _image(self.image)
        if not _REPOSITORY.fullmatch(self.repository):
            raise ValueError(f"{self.image}: repository must be owner/name")


@dataclass(frozen=True, kw_only=True)
class Signed(_Entry):
    tier: ClassVar[Tier] = Tier.SIGNED
    # Keyless: the certificate identity, written out or as an anchored pattern, and the OIDC issuer that must have issued it.
    identity: str | None = None
    identity_regexp: str | None = None
    issuer: str | None = None
    # With a key: the committed public key file, in place of an identity and an issuer.
    key: str | None = None

    def __post_init__(self) -> None:
        _image(self.image)
        keyless = [value for value in (self.identity, self.identity_regexp, self.issuer) if value]
        if self.key:
            if keyless:
                raise ValueError(f"{self.image}: a public key and a certificate identity are alternatives, not both")
            if not _KEY.fullmatch(self.key):
                raise ValueError(f"{self.image}: key must be a .pub file directly under {KEYS}")
            return
        if not (self.identity or self.identity_regexp):
            raise ValueError(f"{self.image}: name the certificate identity, or the public key; an entry that fixes neither would accept any signer")
        if self.identity and self.identity_regexp:
            raise ValueError(f"{self.image}: give the certificate identity written out or as a pattern, not both")
        if not (self.issuer and self.issuer.startswith("https://")):
            raise ValueError(f"{self.image}: issuer must be an https URL")
        if any(c.isspace() for c in (self.identity or self.identity_regexp or "")):
            raise ValueError(f"{self.image}: the certificate identity must not contain whitespace")
        if self.identity_regexp:
            self._check_pattern(self.identity_regexp)

    def _check_pattern(self, pattern: str) -> None:
        if not _ANCHORED_IDENTITY.fullmatch(pattern) or not pattern.endswith("$") or pattern.endswith("\\$"):
            raise ValueError(f"{self.image}: identity_regexp must be anchored, from ^https:// and a literal host to $")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"{self.image}: identity_regexp is not a pattern: {exc}") from exc


@dataclass(frozen=True, kw_only=True)
class Unsigned(_Entry):
    tier: ClassVar[Tier] = Tier.UNSIGNED
    reason: str

    def __post_init__(self) -> None:
        _image(self.image)
        if not self.reason.strip():
            raise ValueError(f"{self.image}: say why there is nothing to verify this image against")


Entry = Attested | Signed | Unsigned

_ACTIONS = "https://token.actions.githubusercontent.com"
_NO_STATEMENT = "no signature or attestation from the publisher was found that ties the image to an identity this repository can fix"
ENTRIES: tuple[Entry, ...] = (
    Attested(image="ghcr.io/lissy93/dashy", repository="Lissy93/dashy"),
    Signed(
        image="openbao/openbao",
        identity_regexp=r"^https://github\.com/openbao/openbao/\.github/workflows/release-images\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$",
        issuer=_ACTIONS,
    ),
    # A reusable workflow at a branch: any commit to that branch of smallstep/workflows can sign, which is all the publisher offers.
    Signed(
        image="smallstep/step-ca", identity="https://github.com/smallstep/workflows/.github/workflows/docker-buildx-push.yml@refs/heads/main", issuer=_ACTIONS
    ),
    Signed(
        image="smallstep/step-cli", identity="https://github.com/smallstep/workflows/.github/workflows/docker-buildx-push.yml@refs/heads/main", issuer=_ACTIONS
    ),
    Signed(image="curlimages/curl", key=f"{KEYS}/curl.pub"),
    Unsigned(image="ghcr.io/11notes/kms", reason="its workflow requests an attestation and GitHub holds none for the pinned digest"),
    Unsigned(image="ghcr.io/11notes/kms-gui", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/chrislusf/seaweedfs", reason="a comment in its workflow says a signature is attached, and no signing step is in the file it is in"),
    Unsigned(
        image="ghcr.io/henrygd/beszel/beszel", reason="it requests a BuildKit SBOM and provenance, which nothing ties to an identity, and has no signing step"
    ),
    Unsigned(
        image="ghcr.io/henrygd/beszel/beszel-agent",
        reason="it requests a BuildKit SBOM and provenance, which nothing ties to an identity, and has no signing step",
    ),
    Unsigned(image="ghcr.io/itzg/minecraft-server", reason="its build sets provenance off and has no attestation or signing step"),
    Unsigned(image="rclone/rclone", reason="its build sets provenance off, and the pinned digest has no signature or attestation from its owner"),
    Unsigned(image="ubuntu/bind9", reason="no signing or attestation step was found, and the pinned digest has no signature or attestation from its owner"),
    Unsigned(image="quxfoo/wastebin", reason="no signing or attestation step was found, and the pinned digest has no signature or attestation from its owner"),
    Unsigned(image="twinproduction/gatus", reason="its release workflow has no signing or attestation step"),
    Attested(image="ghcr.io/wenenhoe/caddy-digitalocean", repository="wenenhoe/homelab"),
    Attested(image="ghcr.io/wenenhoe/coderabbit-review", repository="wenenhoe/homelab"),
    Attested(image="ghcr.io/wenenhoe/gatus", repository="wenenhoe/homelab"),
    Attested(image="ghcr.io/wenenhoe/molecule-dind", repository="wenenhoe/homelab"),
    Attested(image="ghcr.io/wenenhoe/wastebin", repository="wenenhoe/homelab"),
    Unsigned(image="alpine", reason=_NO_STATEMENT),
    Unsigned(image="amazon/aws-cli", reason=_NO_STATEMENT),
    Unsigned(image="busybox", reason=_NO_STATEMENT),
    Unsigned(image="caddy", reason=_NO_STATEMENT),
    Unsigned(image="geerlingguy/docker-ubuntu2604-ansible", reason=_NO_STATEMENT),
    Unsigned(image="hello-world", reason=_NO_STATEMENT),
    Unsigned(image="ubuntu", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/alam00000/bentopdf-simple", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/bluemap-minecraft/bluemap", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/imputnet/cobalt", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/itzg/mc-backup", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/librespeed/speedtest", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/lldap/lldap", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/mermaid-js/mermaid-cli/mermaid-cli", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/offen/docker-volume-backup", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/renovatebot/renovate", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/shlinkio/shlink", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/sigstore/cosign/cosign", reason="the identity its publisher signs it with is not recorded here"),
    Unsigned(image="ghcr.io/shlinkio/shlink-web-client", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/tecnativa/docker-socket-proxy", reason=_NO_STATEMENT),
    Unsigned(image="ghcr.io/tinyauthapp/tinyauth", reason=_NO_STATEMENT),
)


def validate(entries: Iterable[Entry]) -> None:
    """Raise ValueError when two entries name one image repository: a digest could then pass on either one's terms."""
    seen: dict[tuple[str, str], str] = {}
    for entry in entries:
        if entry.registry_key in seen:
            raise ValueError(f"{entry.image} and {seen[entry.registry_key]} name the same image repository")
        seen[entry.registry_key] = entry.image
