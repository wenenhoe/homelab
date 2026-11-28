"""The hooks a machine without a need skips."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from deliver_series.repository import HOMELAB

# A probe returns None when the need is met, else what is missing.
Probe = Callable[[], str | None]


def skipped(probes: Mapping[str, Probe]) -> dict[str, str]:
    """The hooks to skip, each with its reason: those whose need its probe found missing, and no others."""
    skips: dict[str, str] = {}
    for need in HOMELAB.needs:
        if (missing := probes[need.name]()) is not None:
            skips.update(dict.fromkeys(need.hooks, f"{need.name}: {missing}"))
    return skips
