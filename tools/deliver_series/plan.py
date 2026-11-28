"""The plan of a series: one line per layer, and the numbers its layers take."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from land_series.manifest import RESERVED_SLUGS, SLUG, TITLE_FORM, TITLE_MAX, SeriesError, parse_series

MAX_NUMBER = 9999
MAX_COMMITS = 26  # a layer's commits take the letters a to z


class PlanError(Exception):
    """The plan cannot be used, or the series files it follows cannot be read."""


@dataclass(frozen=True)
class PlannedLayer:
    """One pull request: its slug, how many commits it holds, and its title."""

    slug: str
    count: int
    title: str | None


def check_title(title: str, where: str) -> None:
    if len(title) > TITLE_MAX:
        raise PlanError(f"{where}: the title is {len(title)} characters; a subject has at most {TITLE_MAX}")
    if not TITLE_FORM.fullmatch(title):
        raise PlanError(f"{where}: {title!r} is not a subject (a Conventional Commits type, then lowercase text after the colon)")


def parse_plan(text: str) -> list[PlannedLayer]:
    """The layers a plan names, in order. A line is `<slug> <number of commits> [<title>]`; blank lines and `#` comments are skipped."""
    layers: list[PlannedLayer] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"plan line {number}"
        words = line.split(maxsplit=2)
        if len(words) < 2:
            raise PlanError(f"{where}: a line is a slug, the number of commits and, for a layer of several, a title")
        slug, count_word = words[0], words[1]
        title = words[2].strip() if len(words) == 3 else None
        if not SLUG.fullmatch(slug) or slug in RESERVED_SLUGS:
            raise PlanError(f"{where}: {slug!r} is not a branch slug (lowercase words joined by hyphens, and not a protected branch)")
        if any(layer.slug == slug for layer in layers):
            raise PlanError(f"{where}: the slug {slug!r} is used twice; one slug is one pull request")
        if not re.fullmatch(r"[1-9]\d*", count_word) or int(count_word) > MAX_COMMITS:
            raise PlanError(f"{where}: {count_word!r} is not a number of commits (1 to {MAX_COMMITS})")
        count = int(count_word)
        if title is None and count > 1:
            raise PlanError(f"{where}: a layer of {count} commits needs a title, since its first commit names a step and not the layer")
        if title is not None:
            check_title(title, where)
        layers.append(PlannedLayer(slug, count, title))
    if not layers:
        raise PlanError("the plan names no layer")
    return layers


def numbering_after(files: list[Path]) -> tuple[int, set[str]]:
    """The number the first layer takes, and the slugs already taken, given the series files that are not merged yet.

    Numbering starts at 1 with none; otherwise after the highest number any of them uses.
    """
    highest, slugs = 0, set()
    for path in files:
        try:
            layers = parse_series(path.read_bytes(), str(path))
        except (OSError, SeriesError) as error:
            raise PlanError(f"cannot read the series file {path}: {error}") from error
        for layer in layers:
            highest = max(highest, int(layer.number))
            slugs.add(layer.slug)
    return highest + 1, slugs


def check_numbers(first: int, layers: list[PlannedLayer], taken: set[str]) -> None:
    if first + len(layers) - 1 > MAX_NUMBER:
        raise PlanError(f"{len(layers)} layers from {first:04d} run past {MAX_NUMBER:04d}")
    if reused := sorted(layer.slug for layer in layers if layer.slug in taken):
        raise PlanError(f"the slug {reused[0]!r} is already used by a series file named as not merged; a slug is not reused")
