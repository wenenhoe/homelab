"""Read a series file: a manifest of layers, then their patches as one mbox.

    0001a first-slug
    0001b second-slug
    0002a inserted-slug after=0001a

    From <commit> Mon Sep 17 00:00:00 2001
    ...one `git format-patch` message per layer, in the manifest's order...

A manifest line is a layer id (four digits and a letter, the patch naming scheme), a branch slug, and optionally
`after=ID` or `before=ID` to place a layer relative to another. Blank lines and `#` comments are skipped.
Layers land in id order unless placed.

Standard library only: the maintainer runs this with whatever python3 is at hand.
"""

from __future__ import annotations

import email
import email.policy
import email.utils
import re
from dataclasses import dataclass

LAYER_ID = re.compile(r"\d{4}[a-z]")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_ENVELOPE = re.compile(rb"^From [0-9a-f]{40,64} ", re.MULTILINE)
_SUBJECT_TAG = re.compile(r"^\[[^\]]*\]\s*")
_DIFF_HEADER = re.compile(r"^diff --git (.*)$", re.MULTILINE)
_PLACEMENT_KEYS = ("after", "before")


class SeriesError(Exception):
    """The series file cannot be read, or its layers cannot be put in an order."""


@dataclass(frozen=True)
class Layer:
    id: str
    slug: str
    patch: bytes
    subject: str
    authored: int
    diff_headers: tuple[str, ...]
    source: str
    after: str | None = None
    before: str | None = None


def parse_series(data: bytes, source: str = "series") -> list[Layer]:
    """The layers of one series file, in the order the file lists them."""
    starts = [match.start() for match in _ENVELOPE.finditer(data)]
    if not starts:
        raise SeriesError(f"{source}: no patches (an mbox starts with a 'From <commit> ' line)")
    entries = _manifest_entries(data[: starts[0]].decode("utf-8", errors="replace"), source)
    chunks = [data[begin:end] for begin, end in zip(starts, [*starts[1:], len(data)], strict=True)]
    if len(entries) != len(chunks):
        raise SeriesError(f"{source}: the manifest lists {len(entries)} layers but the mbox holds {len(chunks)} patches")
    return [_layer(entry, chunk, source) for entry, chunk in zip(entries, chunks, strict=True)]


def _manifest_entries(text: str, source: str) -> list[tuple[str, str, dict[str, str]]]:
    entries = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"{source}:{number}"
        words = line.split()
        if len(words) < 2:
            raise SeriesError(f"{where}: a layer line is an id and a branch slug")
        layer_id, slug, *options = words
        if not LAYER_ID.fullmatch(layer_id):
            raise SeriesError(f"{where}: {layer_id!r} is not a layer id (four digits and a lowercase letter)")
        if not SLUG.fullmatch(slug):
            raise SeriesError(f"{where}: {slug!r} is not a branch slug (lowercase words joined by hyphens)")
        placement = {}
        for option in options:
            key, _, value = option.partition("=")
            if key not in _PLACEMENT_KEYS or not LAYER_ID.fullmatch(value):
                raise SeriesError(f"{where}: {option!r} is not after=ID or before=ID")
            placement[key] = value
        if len(placement) > 1:
            raise SeriesError(f"{where}: layer {layer_id} has both after and before")
        entries.append((layer_id, slug, placement))
    return entries


def _layer(entry: tuple[str, str, dict[str, str]], chunk: bytes, source: str) -> Layer:
    layer_id, slug, placement = entry
    message = email.message_from_bytes(chunk, policy=email.policy.default)
    subject, date = message["Subject"], message["Date"]
    if subject is None or date is None:
        raise SeriesError(f"{source}: the patch for layer {layer_id} has no Subject or Date header")
    try:
        authored = int(email.utils.parsedate_to_datetime(str(date)).timestamp())
    except (TypeError, ValueError) as error:
        raise SeriesError(f"{source}: the patch for layer {layer_id} has an unreadable Date: {date}") from error
    headers = tuple(_DIFF_HEADER.findall(chunk.decode("utf-8", errors="replace")))
    return Layer(
        id=layer_id,
        slug=slug,
        patch=chunk,
        subject=" ".join(_SUBJECT_TAG.sub("", str(subject)).split()),
        authored=authored,
        diff_headers=headers,
        source=source,
        **placement,
    )


def order_layers(layers: list[Layer]) -> list[Layer]:
    """The layers in landing order: by id, with a placed layer moved to just after or before its target."""
    by_id: dict[str, Layer] = {}
    for layer in layers:
        if layer.id in by_id:
            raise SeriesError(f"layer {layer.id} is listed twice ({by_id[layer.id].source} and {layer.source}); a fix takes the next letter")
        by_id[layer.id] = layer
    slugs: dict[str, str] = {}
    for layer in layers:
        if layer.slug in slugs:
            raise SeriesError(f"layers {slugs[layer.slug]} and {layer.id} share the branch slug {layer.slug!r}")
        slugs[layer.slug] = layer.id
    ordered = sorted(layers, key=lambda layer: layer.id)
    for layer in sorted((layer for layer in layers if layer.after or layer.before), key=lambda layer: layer.id):
        target_id = layer.after or layer.before
        if target_id == layer.id or target_id not in by_id:
            raise SeriesError(f"layer {layer.id} is placed relative to {target_id}, which is not in the series")
        ordered.remove(layer)
        position = ordered.index(by_id[target_id])
        ordered.insert(position + 1 if layer.after else position, layer)
    position_of = {layer.id: index for index, layer in enumerate(ordered)}
    for layer in ordered:
        if layer.after and position_of[layer.id] < position_of[layer.after]:
            raise SeriesError(f"layer {layer.id} must come after {layer.after}, which another placement moved past it")
        if layer.before and position_of[layer.id] > position_of[layer.before]:
            raise SeriesError(f"layer {layer.id} must come before {layer.before}, which another placement moved before it")
    return ordered
