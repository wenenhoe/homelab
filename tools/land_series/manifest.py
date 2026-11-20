"""Read a series file: a manifest of commits, then their patches as one mbox.

    0001a first-slug
    0001b first-slug
    0002a second-slug

    From <commit> Mon Sep 17 00:00:00 2001
    ...one `git format-patch` message per manifest line, in the manifest's order...

A manifest line is a patch id (four digits and a letter, the patch naming scheme) and a branch slug. The number is a pull
request and the letter a commit in it, so the commits that share a number share one slug, and a slug belongs to one number.
Blank lines and `#` comments are skipped, except two lines. A `# base: <branch>` line names the branch the series lands on (`develop`, say)
and `--base` overrides it. A `# title <number>: <subject>` line names the title of the pull request with that number, which is otherwise
its first commit's subject. Commits land in id order, which the naming scheme keeps in step with the order they
were written in; a pull request's commits are its branch, in that order.

Standard library only: the maintainer runs this with whatever python3 is at hand.
"""

from __future__ import annotations

import email
import email.policy
import email.utils
import re
from dataclasses import dataclass

LAYER_ID = re.compile(r"\d{4}[a-z]")
BASE_LINE = re.compile(r"#\s*base:(.*)")
BASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
TITLE_LINE = re.compile(r"#\s*title\b(.*)")
TITLE_BODY = re.compile(r"(\d{4}):\s*(.+)")
# The form of a commit subject: Conventional Commits, lowercase after the colon.
TITLE_FORM = re.compile(r"[a-z]+(?:\([^()\s]+\))?!?: [^\sA-Z].*")
TITLE_MAX = 72
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_ENVELOPE = re.compile(rb"^From [0-9a-f]{40,64} ", re.MULTILINE)
_SUBJECT_TAG = re.compile(r"^\[[^\]]*\]\s*")
# Branches the rulesets protect; a pull request's branch is pushed, force-pushed and deleted, so it is never one of these.
RESERVED_SLUGS = ("main", "maintenance", "develop")


class SeriesError(Exception):
    """The series file cannot be read, or its layers cannot be put in an order."""


@dataclass(frozen=True)
class Layer:
    """One commit of a pull request."""

    id: str
    slug: str
    patch: bytes
    subject: str
    authored: int
    source: str
    # The title the manifest names for this commit's pull request, when it names one.
    title: str | None = None

    @property
    def number(self) -> str:
        return self.id[:4]


@dataclass(frozen=True)
class Pull:
    """The commits that share a number: one branch, one pull request."""

    number: str
    slug: str
    layers: tuple[Layer, ...]

    @property
    def title(self) -> str:
        """The title the manifest names, else the first commit's subject. It becomes the merge commit's body and so the history's one line for the change."""
        return next((layer.title for layer in self.layers if layer.title), self.layers[0].subject)


def parse_series(data: bytes, source: str = "series") -> list[Layer]:
    """The layers of one series file, in the order the file lists them."""
    starts = [match.start() for match in _ENVELOPE.finditer(data)]
    if not starts:
        raise SeriesError(f"{source}: no patches (an mbox starts with a 'From <commit> ' line)")
    manifest = data[: starts[0]].decode("utf-8", errors="replace")
    entries = _manifest_entries(manifest, source)
    titles = _manifest_titles(manifest, {layer_id[:4] for layer_id, _ in entries}, source)
    chunks = [data[begin:end] for begin, end in zip(starts, [*starts[1:], len(data)], strict=True)]
    if len(entries) != len(chunks):
        raise SeriesError(f"{source}: the manifest lists {len(entries)} layers but the mbox holds {len(chunks)} patches")
    return [_layer(entry, chunk, source, titles.get(entry[0][:4])) for entry, chunk in zip(entries, chunks, strict=True)]


def parse_base(data: bytes, source: str = "series") -> str | None:
    """The branch a `# base: <branch>` line in the manifest names, or None when it has none; two different ones are refused."""
    starts = [match.start() for match in _ENVELOPE.finditer(data)]
    text = data[: starts[0] if starts else len(data)].decode("utf-8", errors="replace")
    bases = set()
    for number, raw in enumerate(text.splitlines(), start=1):
        if found := BASE_LINE.fullmatch(raw.strip()):
            name = found.group(1).strip()
            if not BASE_NAME.fullmatch(name):
                raise SeriesError(f"{source}:{number}: {name!r} is not a branch name; write `# base: develop`")
            bases.add(name)
    if len(bases) > 1:
        raise SeriesError(f"{source}: the manifest names more than one base ({', '.join(sorted(bases))})")
    return bases.pop() if bases else None


def _manifest_entries(text: str, source: str) -> list[tuple[str, str]]:
    entries = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"{source}:{number}"
        words = line.split()
        if len(words) != 2:
            raise SeriesError(f"{where}: a manifest line is a patch id and a branch slug")
        layer_id, slug = words
        if not LAYER_ID.fullmatch(layer_id):
            raise SeriesError(f"{where}: {layer_id!r} is not a layer id (four digits and a lowercase letter)")
        if not SLUG.fullmatch(slug):
            raise SeriesError(f"{where}: {slug!r} is not a branch slug (lowercase words joined by hyphens)")
        if slug in RESERVED_SLUGS:
            raise SeriesError(f"{where}: {slug!r} is a protected branch, not a layer branch")
        entries.append((layer_id, slug))
    return entries


def _manifest_titles(text: str, numbers: set[str], source: str) -> dict[str, str]:
    """The pull request titles the manifest names, by number; a line that is not a well-formed title for a listed number is refused."""
    titles: dict[str, str] = {}
    for line_number, raw in enumerate(text.splitlines(), start=1):
        found = TITLE_LINE.fullmatch(raw.strip())
        if not found:
            continue
        where = f"{source}:{line_number}"
        named = TITLE_BODY.fullmatch(found.group(1).strip())
        if not named:
            raise SeriesError(f"{where}: write a title as `# title 0001: docs(scope): say what the pull request is for`")
        number, title = named.group(1), named.group(2).strip()
        if number not in numbers:
            raise SeriesError(f"{where}: the manifest lists no layer {number}, so there is no pull request to title")
        if number in titles:
            raise SeriesError(f"{where}: the pull request {number} is given a second title")
        if len(title) > TITLE_MAX:
            raise SeriesError(f"{where}: the title is {len(title)} characters; a subject has at most {TITLE_MAX}")
        if not TITLE_FORM.fullmatch(title):
            raise SeriesError(f"{where}: {title!r} is not a subject (a Conventional Commits type, then lowercase text after the colon)")
        titles[number] = title
    return titles


def _layer(entry: tuple[str, str], chunk: bytes, source: str, title: str | None) -> Layer:
    layer_id, slug = entry
    message = email.message_from_bytes(chunk, policy=email.policy.default)
    subject, date = message["Subject"], message["Date"]
    if subject is None or date is None:
        raise SeriesError(f"{source}: the patch for layer {layer_id} has no Subject or Date header")
    try:
        authored = int(email.utils.parsedate_to_datetime(str(date)).timestamp())
    except (TypeError, ValueError) as error:
        raise SeriesError(f"{source}: the patch for layer {layer_id} has an unreadable Date: {date}") from error
    return Layer(
        id=layer_id,
        slug=slug,
        patch=chunk,
        subject=" ".join(_SUBJECT_TAG.sub("", str(subject)).split()),
        authored=authored,
        source=source,
        title=title,
    )


def order_layers(layers: list[Layer]) -> list[Layer]:
    """The commits in landing order, which is id order; an id used twice, or a number and a branch slug that do not pair up, is refused."""
    by_id: dict[str, Layer] = {}
    slug_of_number: dict[str, str] = {}
    number_of_slug: dict[str, str] = {}
    title_of_number: dict[str, str] = {}
    for layer in layers:
        if layer.id in by_id:
            raise SeriesError(f"{layer.id} is listed twice ({by_id[layer.id].source} and {layer.source}); a fix takes the next letter")
        if slug_of_number.setdefault(layer.number, layer.slug) != layer.slug:
            raise SeriesError(
                f"{layer.number} has the branch slugs {slug_of_number[layer.number]!r} and {layer.slug!r}: a number is one pull request, "
                "so give each pull request its own number"
            )
        if number_of_slug.setdefault(layer.slug, layer.number) != layer.number:
            raise SeriesError(f"the branch slug {layer.slug!r} is used by {number_of_slug[layer.slug]} and {layer.number}; one slug is one number")
        if layer.title and title_of_number.setdefault(layer.number, layer.title) != layer.title:
            raise SeriesError(f"{layer.number} has the titles {title_of_number[layer.number]!r} and {layer.title!r}: a pull request has one title")
        by_id[layer.id] = layer
    return sorted(layers, key=lambda layer: layer.id)


def group_pulls(layers: list[Layer]) -> list[Pull]:
    """The pull requests of commits already in landing order."""
    pulls: list[Pull] = []
    for layer in layers:
        if pulls and pulls[-1].number == layer.number:
            pulls[-1] = Pull(layer.number, layer.slug, (*pulls[-1].layers, layer))
        else:
            pulls.append(Pull(layer.number, layer.slug, (layer,)))
    return pulls
