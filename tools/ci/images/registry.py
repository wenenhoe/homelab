#!/usr/bin/env python3
"""The images this repo builds and publishes, and the tag each one gets.

Each image's name and how its tag is derived live here once. The build
workflows ask this module for their tags instead of grepping the
Dockerfile themselves, the CI build and boot-test steps look images up
here, and `check-pins` fails when anything that names one disagrees:

- a compose file pinning `ghcr.io/wenenhoe/<name>:<tag>` where the tag is
  not the one the build workflow will publish from the Dockerfile;
- a Molecule scenario's `image:` naming a tag that isn't published;
- an image no entry here describes, or an entry with no Dockerfile, or a
  `docker/<app>/Dockerfile` with no entry.

A tag is read from the Dockerfile, so a Renovate bump to it is what
changes it: the compose pin must move in the same change.

Subcommands (from tools/: python -m ci.images.registry ...):
  tags <image>   writes version=<tag> and tags=<comma-separated refs>
  check-pins     lists every disagreement and exits 1 if there is any
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ci.output import write_output

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = "ghcr.io/wenenhoe"

_FROM = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+\S+)?\s*$", re.IGNORECASE)
_VERSION = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_COMPOSE_IMAGE = re.compile(rf"^\s*image:\s*[\"']?{re.escape(REGISTRY)}/([^\s:\"']+)(?::([^\s\"']+))?", re.MULTILINE)
_MOLECULE_IMAGE = re.compile(rf"^\s*image:\s*{re.escape(REGISTRY)}/([^\s:]+):(\S+)\s*$", re.MULTILINE)


class ImageError(Exception):
    """A Dockerfile or image entry doesn't say what the tag needs it to."""


# Dockerfile text -> version tag.
TagSource = Callable[[str], str]


def _split_ref(ref: str) -> tuple[str, str | None]:
    """`name[:tag]` -> (name, tag); a colon before the last `/` is a registry port, not a tag."""
    head, sep, tail = ref.rpartition(":")
    if sep and "/" not in tail:
        return head, tail
    return ref, None


def _from_images(text: str) -> list[tuple[str, str | None]]:
    """(image, tag) of every FROM instruction, in order."""
    return [_split_ref(match.group(1)) for line in text.splitlines() if (match := _FROM.match(line))]


def _checked(tag: str | None, what: str, pattern: re.Pattern[str] = _VERSION) -> str:
    if tag is None or not pattern.match(tag):
        raise ImageError(f"{what} must be a version like 1.2.3, got {tag!r}")
    return tag


def final_from(image: str) -> TagSource:
    """The tag of the Dockerfile's last FROM, which must be `image`."""

    def source(text: str) -> str:
        froms = _from_images(text)
        if not froms:
            raise ImageError("no FROM instruction")
        name, tag = froms[-1]
        if name != image:
            raise ImageError(f"final FROM is {name!r}, expected {image!r}")
        return _checked(tag, f"the tag on the final FROM {image}")

    return source


def from_image(image: str) -> TagSource:
    """The tag of the one FROM naming `image`."""

    def source(text: str) -> str:
        matches = [tag for name, tag in _from_images(text) if name == image]
        if len(matches) != 1:
            raise ImageError(f"expected exactly one FROM {image}, found {len(matches)}")
        return _checked(matches[0], f"the tag on FROM {image}")

    return source


def arg_version(arg: str) -> TagSource:
    """The value of the one `ARG <arg>=X.Y.Z` line."""

    def source(text: str) -> str:
        lines = [line for line in text.splitlines() if line.startswith(f"ARG {arg}=")]
        if len(lines) != 1:
            raise ImageError(f"expected exactly one 'ARG {arg}=X.Y.Z', found {len(lines)}")
        return _checked(lines[0].removeprefix(f"ARG {arg}="), f"ARG {arg}", _SEMVER)

    return source


def constant(tag: str) -> TagSource:
    return lambda text: tag


@dataclass(frozen=True)
class Image:
    key: str  # docker/<key>/ for a deployed app; the CLI name either way
    name: str  # published as ghcr.io/wenenhoe/<name>
    context: str  # repo-relative build context, holding the Dockerfile
    source: TagSource
    extra_tags: tuple[str, ...] = ()  # published alongside the version tag

    def dockerfile(self, root: Path) -> Path:
        return root / self.context / "Dockerfile"


IMAGES: dict[str, Image] = {
    image.key: image
    for image in (
        Image("caddy", "caddy-digitalocean", "docker/caddy", final_from("caddy")),
        Image("wastebin", "wastebin", "docker/wastebin", from_image("quxfoo/wastebin")),
        Image("molecule-dind", "molecule-dind", "docker/molecule-dind", constant("latest")),
        Image("coderabbit-review", "coderabbit-review", "tools/coderabbit-review", arg_version("CODERABBIT_VERSION"), extra_tags=("latest",)),
    )
}


def lookup(key: str) -> Image:
    try:
        return IMAGES[key]
    except KeyError:
        raise ImageError(f"no image entry for {key!r} in ci.images.registry.IMAGES (known: {', '.join(sorted(IMAGES))})") from None


def resolve_version(root: Path, image: Image) -> str:
    path = image.dockerfile(root)
    try:
        text = path.read_text()
    except OSError as exc:
        raise ImageError(f"{image.key}: can't read {path}: {exc}") from exc
    try:
        return image.source(text)
    except ImageError as exc:
        raise ImageError(f"{image.key}: {path.relative_to(root)}: {exc}") from exc


def refs(root: Path, image: Image) -> list[str]:
    """Every reference the build publishes: the version tag first, then the extras."""
    tags = [resolve_version(root, image), *image.extra_tags]
    return [f"{REGISTRY}/{image.name}:{tag}" for tag in dict.fromkeys(tags)]


def check_pins(root: Path) -> list[str]:
    """Every place that names an image and disagrees with what gets published."""
    errors: list[str] = []
    by_name = {image.name: image for image in IMAGES.values()}
    published: dict[str, set[str]] = {}
    for image in IMAGES.values():
        if not image.dockerfile(root).is_file():
            errors.append(f"{image.key}: {image.context}/Dockerfile doesn't exist")
            continue
        try:
            published[image.name] = {ref.rsplit(":", 1)[1] for ref in refs(root, image)}
        except ImageError as exc:
            errors.append(str(exc))

    for dockerfile in sorted((root / "docker").glob("*/Dockerfile")):
        if dockerfile.parent.name not in IMAGES:
            errors.append(f"docker/{dockerfile.parent.name}/Dockerfile has no entry in ci.images.registry.IMAGES")

    for compose in sorted((root / "docker").glob("*/compose.yaml*")):
        for name, tag in _COMPOSE_IMAGE.findall(compose.read_text()):
            where = compose.relative_to(root)
            if name not in by_name:
                errors.append(f"{where}: pins {REGISTRY}/{name}, which no image entry publishes")
            elif name in published:
                version = resolve_version(root, by_name[name])
                if tag != version:
                    errors.append(f"{where}: pins {REGISTRY}/{name}:{tag or '(no tag)'}, but the Dockerfile publishes {version}")

    for molecule in sorted((root / "ansible/roles").glob("*/molecule/*/molecule.yml")):
        for name, tag in _MOLECULE_IMAGE.findall(molecule.read_text()):
            where = molecule.relative_to(root)
            if name not in by_name:
                errors.append(f"{where}: uses {REGISTRY}/{name}, which no image entry publishes")
            elif name in published and tag not in published[name]:
                errors.append(f"{where}: uses {REGISTRY}/{name}:{tag}, but the published tags are {sorted(published[name])}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    tags = sub.add_parser("tags")
    tags.add_argument("image")
    sub.add_parser("check-pins")
    args = parser.parse_args(argv)
    try:
        if args.command == "tags":
            image = lookup(args.image)
            published = refs(REPO_ROOT, image)
            print("\n".join(published))
            write_output("version", resolve_version(REPO_ROOT, image))
            write_output("tags", ",".join(published))
            return 0
        errors = check_pins(REPO_ROOT)
    except ImageError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print("Every image pin matches what its Dockerfile publishes.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
