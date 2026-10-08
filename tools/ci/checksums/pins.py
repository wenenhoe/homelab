"""Reading pinned hashes and versions out of the repository, and finding every pin in it.

A pin's version is placed into a URL, and the file it comes from is changed by
pull requests, so a version is accepted only in the shape a release version has.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ci.checksums.registry import Entry, Location

SHA256 = re.compile(r"[0-9a-f]{64}")
VERSION = re.compile(r"[0-9][0-9A-Za-z.+_-]*")
# The trees a pinned download can sit in. Docs are left out: they quote example hashes.
SCAN_ROOTS = ("ansible", "docker", "tools", ".github")
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}

_VALUE = r"""(?:"(?P<double>[^"\n]*)"|'(?P<single>[^'\n]*)'|(?P<bare>[^\s#"']+))"""
_FOUND_YAML = re.compile(
    r"^[ \t]*(?:-[ \t]+)?(?P<name>\w*sha256\w*)[ \t]*:[ \t]*[\"']?(?P<value>[0-9a-f]{64})[\"']?[ \t]*(?:#.*)?$", re.MULTILINE | re.IGNORECASE
)
_FOUND_ARG = re.compile(r"^[ \t]*ARG[ \t]+(?P<name>\w*sha256\w*)=[\"']?(?P<value>[0-9a-f]{64})[\"']?[ \t]*$", re.MULTILINE | re.IGNORECASE)
_FOUND_INLINE = re.compile(r"checksum:[ \t]*[\"']?sha256:(?P<value>[0-9a-f]{64})", re.IGNORECASE)
YAML_SUFFIXES = (".yaml", ".yml", ".j2")
# Named, not written inline: `ruff format` targets 3.14 and drops the parentheses from a bare
# `except (A, B):`, which older Pythons (the runner's python3) can't parse.
_READ_ERRORS = (OSError, UnicodeDecodeError)


class PinError(Exception):
    """A pin or version can't be read, or isn't in the shape it must be."""


@dataclass(frozen=True)
class Found:
    path: str
    name: str  # the key or ARG naming the pin; `checksum:` for a literal written into a task
    value: str


def is_dockerfile(name: str) -> bool:
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile")


def _pattern(path: str, name: str) -> re.Pattern[str]:
    if is_dockerfile(Path(path).name):
        return re.compile(rf"^[ \t]*ARG[ \t]+{re.escape(name)}={_VALUE}[ \t]*$", re.MULTILINE)
    return re.compile(rf"^{re.escape(name)}:[ \t]*{_VALUE}[ \t]*(?:#.*)?$", re.MULTILINE)


def read_value(root: Path, location: Location) -> str:
    try:
        text = (root / location.path).read_text()
    except _READ_ERRORS as exc:
        raise PinError(f"can't read {location.path}: {exc}") from exc
    matches = list(_pattern(location.path, location.name).finditer(text))
    if not matches:
        raise PinError(f"{location.path} has no {location.name} set to a plain value")
    if len(matches) > 1:
        raise PinError(f"{location.path} sets {location.name} more than once")
    return next(value for value in matches[0].group("double", "single", "bare") if value is not None)


def read_pin(root: Path, entry: Entry) -> tuple[str, str]:
    """(version, sha256) as the repository pins them for this entry."""
    version = read_value(root, entry.version)
    pin = read_value(root, entry.pin)
    if not VERSION.fullmatch(version):
        raise PinError(f"{entry.version.name} in {entry.version.path} is {version!r}, which isn't a release version")
    if not SHA256.fullmatch(pin):
        raise PinError(f"{entry.pin.name} in {entry.pin.path} isn't a lower-case sha256")
    return version, pin


def _walk(root: Path):
    for tree in SCAN_ROOTS:
        for dirpath, dirnames, filenames in os.walk(root / tree):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                yield Path(dirpath) / name


def discover(root: Path) -> list[Found]:
    """Every checksum pin written in the trees a download can be pinned in, in whatever form."""
    found: list[Found] = []
    for path in _walk(root):
        if not (is_dockerfile(path.name) or path.name.endswith(YAML_SUFFIXES)):
            continue
        try:
            text = path.read_text()
        except _READ_ERRORS:
            continue
        rel = path.relative_to(root).as_posix()
        if is_dockerfile(path.name):
            found += [Found(rel, m.group("name"), m.group("value")) for m in _FOUND_ARG.finditer(text)]
        else:
            found += [Found(rel, m.group("name"), m.group("value")) for m in _FOUND_YAML.finditer(text)]
            found += [Found(rel, "checksum:", m.group("value")) for m in _FOUND_INLINE.finditer(text)]
    return sorted(found, key=lambda pin: (pin.path, pin.name, pin.value))
