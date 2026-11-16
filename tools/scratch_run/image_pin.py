"""The OPNsense image a QEMU run boots, pinned in the repository because a CI run has no settings file.

A node run takes the image's URL and checksum from the operator's settings; a QEMU run on a runner has none, so the same two values are
read from `tofu/scratch/opnsense/image-pin.yaml`. A setting or a flag still beats the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from utils.unique_key_yaml import UniqueKeyLoader

from scratch_run.settings import IMAGE_CHECKSUM, IMAGE_URL

PIN_FILE = Path(__file__).resolve().parents[2] / "tofu" / "scratch" / "opnsense" / "image-pin.yaml"
URL_RE = re.compile(r"https://[A-Za-z0-9._~:/%+-]+\.img\.bz2")
CHECKSUM_RE = re.compile(r"[0-9a-f]{64}")
KEYS = ("url", "sha256")


class ImagePinError(Exception):
    pass


@dataclass(frozen=True)
class ImagePin:
    url: str
    sha256: str


def image_problems(url: str, checksum: str) -> list[str]:
    """What is wrong with an image URL and checksum, as the node's own scripts judge them."""
    problems = []
    if not URL_RE.fullmatch(url) or "-nano-" not in url.rsplit("/", 1)[-1]:
        problems.append(f"the image URL must be an https:// URL of an OPNsense nano .img.bz2 file (--image-url, or {IMAGE_URL} in the settings)")
    if not CHECKSUM_RE.fullmatch(checksum):
        problems.append(f"the image checksum must be 64 lowercase hexadecimal characters (--image-checksum, or {IMAGE_CHECKSUM} in the settings)")
    return problems


def load_pin(path: Path = PIN_FILE) -> ImagePin:
    try:
        data = yaml.load(path.read_text(), Loader=UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except (OSError, yaml.YAMLError) as error:
        raise ImagePinError(f"{path} cannot be read: {error}") from error
    if not isinstance(data, dict) or set(data) != set(KEYS) or not all(isinstance(data[key], str) for key in KEYS):
        raise ImagePinError(f"{path} must hold exactly the strings `url` and `sha256`")
    problems = image_problems(data["url"], data["sha256"])
    if problems:
        raise ImagePinError(f"{path}: " + "; ".join(problems))
    return ImagePin(data["url"], data["sha256"])
