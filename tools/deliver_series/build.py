"""Check the commits against the plan and write the series file `land_series` reads."""

from __future__ import annotations

import re
import string
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from land_series.manifest import SeriesError, order_layers, parse_series

from deliver_series.form import Commit, problems
from deliver_series.plan import PlannedLayer
from deliver_series.repo import RepoError, patch_of
from deliver_series.repository import HOMELAB, Identity

# `land_series` reads a patch in full before it replays it, which an encoded header or a binary body prevents.
# A line of file content starts with `+`, `-` or a space, so a line that starts with these words is git's own.
UNREADABLE = re.compile(rb"^(GIT binary patch|Binary files .* differ)$", re.MULTILINE)


class BuildError(Exception):
    """A commit does not have the form, or the series cannot be written."""


@dataclass(frozen=True)
class Layer:
    """A planned layer with its number and the commits that fill it."""

    number: int
    plan: PlannedLayer
    commits: tuple[Commit, ...]

    def ids(self) -> list[str]:
        return [f"{self.number:04d}{letter}" for letter in string.ascii_lowercase[: len(self.commits)]]


def assign(plan: Sequence[PlannedLayer], commits: Sequence[Commit], first: int) -> list[Layer]:
    """Give each layer the next commits in order; the plan has to account for every commit."""
    wanted = sum(layer.count for layer in plan)
    if wanted != len(commits):
        raise BuildError(f"the plan holds {wanted} commits and the branch has {len(commits)} above the base")
    layers, at = [], 0
    for offset, planned in enumerate(plan):
        layers.append(Layer(first + offset, planned, tuple(commits[at : at + planned.count])))
        at += planned.count
    return layers


def check_form(layers: Sequence[Layer], maintainer: Identity) -> None:
    """Refuse the series naming every commit that lacks the commit form and what is wrong with it."""
    found = [
        f"{commit.sha[:12]} ({layer.plan.slug}, {commit.subject!r}): {problem}"
        for layer in layers
        for commit in layer.commits
        for problem in problems(commit, maintainer, layer.plan.slug)
    ]
    if found:
        raise BuildError("commits without the commit form:\n" + "\n".join(f"- {line}" for line in found))


def render(layers: Sequence[Layer], base: str, repo: Path) -> bytes:
    """The series file: the manifest, a blank line, then every patch."""
    lines = [] if base == HOMELAB.default_base else [f"# base: {base}"]
    patches = []
    for layer in layers:
        lines.extend(f"{layer_id} {layer.plan.slug}" for layer_id in layer.ids())
        if layer.plan.title:
            lines.append(f"# title {layer.number:04d}: {layer.plan.title}")
        for commit in layer.commits:
            patch = patch_of(repo, commit.sha)
            header = patch.split(b"\n\n", 1)[0]
            if b"=?" in header or b"\nContent-Transfer-Encoding" in header or UNREADABLE.search(patch):
                raise BuildError(f"the patch of {commit.sha[:12]} ({commit.subject!r}) is encoded or binary, so it cannot be read in full before a replay")
            patches.append(patch)
    return ("\n".join(lines) + "\n\n").encode() + b"".join(patches)


def write(layers: Sequence[Layer], base: str, repo: Path, out: Path, suffix: str = "") -> Path:
    """Write the series file in `out` after reading it back the way `land_series` does; `suffix` marks a file that has not passed its checks."""
    try:
        data = render(layers, base, repo)
    except RepoError as error:
        raise BuildError(str(error)) from error
    name = f"{layers[0].number:04d}-{layers[-1].number:04d}.series"
    path = out / f"{name}{suffix}"
    if path.exists() or (out / name).exists():
        raise BuildError(f"{path} exists already")
    try:
        order_layers(parse_series(data, path.name))
    except SeriesError as error:
        raise BuildError(f"the series would not be read by land_series: {error}") from error
    path.write_bytes(data)
    return path
