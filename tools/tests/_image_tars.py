"""Builds `docker save`-shaped archives for the scanner's tests, with no Docker."""

from __future__ import annotations

import io
import json
import struct
import tarfile
from pathlib import Path

CAPABILITY_XATTR = "SCHILY.xattr.security.capability"


def capability_xattr(permitted: int, *, effective: bool = True, revision: int = 2, inheritable: int = 0) -> str:
    """A `security.capability` value as pax carries it: the raw bytes, escaped to str."""
    magic = (revision << 24) | int(effective)
    raw = struct.pack("<I", magic)
    if revision == 1:
        raw += struct.pack("<II", permitted & 0xFFFFFFFF, inheritable & 0xFFFFFFFF)
    else:
        raw += struct.pack("<II", permitted & 0xFFFFFFFF, inheritable & 0xFFFFFFFF)
        raw += struct.pack("<II", permitted >> 32, inheritable >> 32)
    return raw.decode("utf-8", "surrogateescape")


def file_entry(name: str, content: bytes = b"x", mode: int = 0o644, capability: str | None = None) -> tuple:
    return (name, content, mode, capability)


def whiteout(path: str) -> tuple:
    directory, _, name = path.rpartition("/")
    return file_entry(f"{directory}/.wh.{name}", b"", 0o644)


def opaque(directory: str) -> tuple:
    return file_entry(f"{directory}/.wh..wh..opq", b"", 0o644)


def directory_entry(name: str) -> tuple:
    return (name, None, 0o755, None)


def _layer(entries: list[tuple]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as layer:
        for name, content, mode, capability in entries:
            info = tarfile.TarInfo(name)
            info.mode = mode
            if content is None:
                info.type = tarfile.DIRTYPE
                layer.addfile(info)
                continue
            info.size = len(content)
            if capability:
                info.pax_headers = {CAPABILITY_XATTR: capability}
            layer.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def write_image(path: Path, layers: list[list[tuple]]) -> Path:
    """An image archive whose layers apply in the order given."""
    names = [f"layer{number}/layer.tar" for number in range(len(layers))]
    with tarfile.open(path, "w") as image:
        for name, entries in zip(names, layers, strict=True):
            data = _layer(entries)
            info = tarfile.TarInfo(name)
            info.size = len(data)
            image.addfile(info, io.BytesIO(data))
        manifest = json.dumps([{"Config": "config.json", "Layers": names}]).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        image.addfile(info, io.BytesIO(manifest))
    return path
