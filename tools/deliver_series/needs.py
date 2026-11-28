"""What each hook that cannot run everywhere needs from the machine, and the hooks a machine without it skips."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Need:
    name: str
    hooks: tuple[str, ...]


# Every hook of the pre-commit configuration whose id ends in `-docker` is listed, which a test holds.
NEEDS = (
    Need("a Docker daemon", ("dclint-docker", "hadolint-docker", "actionlint-docker")),
    Need("a download of the Go toolchain", ("gitleaks",)),
    Need("the GitHub API", ("zizmor",)),
    Need("the Ansible collections", ("ansible-lint",)),
)

# A probe returns None when the need is met, else what is missing.
Probe = Callable[[], str | None]


def skipped(probes: Mapping[str, Probe]) -> dict[str, str]:
    """The hooks to skip, each with its reason: those whose need its probe found missing, and no others."""
    skips: dict[str, str] = {}
    for need in NEEDS:
        if (missing := probes[need.name]()) is not None:
            skips.update(dict.fromkeys(need.hooks, f"{need.name}: {missing}"))
    return skips
