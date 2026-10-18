"""The digests the tree pins for each image repository.

References are collected the way the image tag check collects them
(ci.images.remote), so a digest pinned in a compose file, a Dockerfile, Ansible
or a Renovate-tracked variable is seen here too. A reference with no digest has
nothing to verify and is left out.

A digest and a repository name go to `gh` and `cosign` as part of one argument,
and both come from files a pull request changes, so a reference is accepted only
in the shape a registry accepts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ci.images.remote import Collected, parse_image

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_COMPONENT = r"[a-z0-9]+(?:[._-]+[a-z0-9]+)*"
_HOST = r"[a-z0-9][a-z0-9.-]*(?::[0-9]+)?"
_REFERENCE = re.compile(rf"{_HOST}/{_COMPONENT}(?:/{_COMPONENT})*@{DIGEST.pattern}")
_DOCKER_HUB = "registry-1.docker.io"


@dataclass(frozen=True)
class Pin:
    registry: str  # the host `ci.images.remote.parse_image` reads, as the tree implies it
    repository: str
    digest: str
    sources: tuple[str, ...]  # repo-relative files that pin it

    @property
    def registry_key(self) -> tuple[str, str]:
        return self.registry, self.repository

    @property
    def reference(self) -> str:
        """`host/repository@digest`, the name `gh` and `cosign` are given. Docker Hub's API host is not the name its images go by."""
        host = "docker.io" if self.registry == _DOCKER_HUB else self.registry
        return f"{host}/{self.repository}@{self.digest}"


def pinned(collected: Collected) -> tuple[list[Pin], list[str]]:
    """(every distinct digest pinned per repository, problems with a reference that can't be verified)."""
    found: dict[tuple[str, str, str], list[str]] = {}
    problems: list[str] = []
    for text, files in collected.images.items():
        if "@" not in text:
            continue
        try:
            image = parse_image(text)
        except ValueError as exc:
            problems.append(f"{text} ({', '.join(files)}): {exc}")
            continue
        pin = Pin(image.registry, image.repository, image.reference, tuple(files))
        if not DIGEST.fullmatch(pin.digest) or not _REFERENCE.fullmatch(pin.reference):
            problems.append(f"{text} ({', '.join(files)}): not a sha256 digest reference a registry accepts")
            continue
        sources = found.setdefault((pin.registry, pin.repository, pin.digest), [])
        sources.extend(source for source in files if source not in sources)
    pins = [Pin(registry, repository, digest, tuple(sources)) for (registry, repository, digest), sources in sorted(found.items())]
    return pins, problems
