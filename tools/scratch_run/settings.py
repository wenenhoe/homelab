"""The settings a run needs, kept in one file outside the repository instead of typed on every command.

The file is `KEY=VALUE` lines, read as text and never run as a shell script. It holds the Proxmox token, so it must be
owned by the user, readable by no one else and outside the repository. A real environment variable beats the file, and a
command-line flag beats both.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

DEFAULT_ENV_FILE = Path("~/.config/homelab/scratch-run.env")
IMAGE_URL = "SCRATCH_RUN_IMAGE_URL"
IMAGE_CHECKSUM = "SCRATCH_RUN_IMAGE_CHECKSUM"
OUT_DIR = "SCRATCH_RUN_OUT_DIR"
KEY_RE = re.compile(r"[A-Z_][A-Z0-9_]*")
TEMPLATE = f"""\
# Settings for `python -m scratch_run`. KEY=VALUE lines; a real environment variable beats this file and a flag beats both.
# This file holds a credential: keep it mode 600 and out of the repository.

# The Proxmox node, as scratch_gateway.sh takes them.
NODE=root@pve
PROXMOX_ENDPOINT=https://pve:8006
PROXMOX_API_TOKEN=user@pam!tokenid=secret

# The master ssh connection to the node is opened for you, and asks for your login once. Its socket defaults to
# ~/.cache/scratch-run/ssh.sock; set SSH_CONTROL_PATH here to put it elsewhere.

# Where a run keeps its state, credentials and results, and the pinned image. The checksum is the .img.bz2's SHA-256.
{OUT_DIR}=~/scratch-run
{IMAGE_URL}=https://pkg.opnsense.org/releases/26.1/OPNsense-26.1.6-nano-amd64.img.bz2
{IMAGE_CHECKSUM}=

# Anything else scratch_gateway.sh reads can go here too: VM_ID, LAN_BRIDGE, WAN_BRIDGE, WAN_VLAN_ID, LOCAL_PORT, WANT_VERSION.
"""


class SettingsError(Exception):
    """The settings file is unsafe or unreadable; the message says how to fix it."""


def read_env_file(path: Path, repo: Path) -> dict[str, str]:
    path = path.expanduser()
    if not path.is_file():
        raise SettingsError(f"{path} does not exist; create it with `python -m scratch_run --init-env`")
    if path.resolve().is_relative_to(repo.resolve()):
        raise SettingsError(f"{path} holds a credential and must be outside the repository")
    info = path.stat()
    if info.st_uid != os.getuid():
        raise SettingsError(f"{path} must be owned by you")
    if info.st_mode & 0o077:
        raise SettingsError(f"{path} must not be readable by anyone else: chmod 600 {path}")
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not KEY_RE.fullmatch(key.strip()):
            raise SettingsError(f"{path} line {number} is not KEY=VALUE with an upper-case KEY")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            values[key.strip()] = os.path.expanduser(value) if value.startswith("~/") else value
    return values


def merge(environ: Mapping[str, str], from_file: Mapping[str, str]) -> dict[str, str]:
    """The file's values under the real environment's."""
    return {**from_file, **environ}


def init_env_file(path: Path) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise SettingsError(f"{path} already exists; edit it, or remove it to start again") from error
    with os.fdopen(descriptor, "w") as handle:
        handle.write(TEMPLATE)
    return path
