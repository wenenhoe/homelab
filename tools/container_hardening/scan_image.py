#!/usr/bin/env python3
"""Static scan of container images for what blocks `no-new-privileges` or `cap_drop`.

Reads each image from `docker save` without running it. Reports setuid and
setgid files, file capabilities, privilege-drop helpers that shell
entrypoints call, and the image's configured user. A compiled entrypoint can
drop privileges without showing up here, so a clean scan is not a pass: boot
the image with the pair set (see docs/topics/deploy/adding-an-app.md,
"Container hardening").

Usage (from tools/):
    python -m container_hardening.scan_image IMAGE [IMAGE ...]
    python -m container_hardening.scan_image --running   # every image a running container uses
"""

from __future__ import annotations

import json
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

# Linux capability numbers, in order; a bit's index is its number.
CAPABILITIES = [
    "CHOWN", "DAC_OVERRIDE", "DAC_READ_SEARCH", "FOWNER", "FSETID", "KILL", "SETGID", "SETUID",
    "SETPCAP", "LINUX_IMMUTABLE", "NET_BIND_SERVICE", "NET_BROADCAST", "NET_ADMIN", "NET_RAW",
    "IPC_LOCK", "IPC_OWNER", "SYS_MODULE", "SYS_RAWIO", "SYS_CHROOT", "SYS_PTRACE", "SYS_PACCT",
    "SYS_ADMIN", "SYS_BOOT", "SYS_NICE", "SYS_RESOURCE", "SYS_TIME", "SYS_TTY_CONFIG", "MKNOD",
    "LEASE", "AUDIT_WRITE", "AUDIT_CONTROL", "SETFCAP", "MAC_OVERRIDE", "MAC_ADMIN", "SYSLOG",
    "WAKE_ALARM", "BLOCK_SUSPEND", "AUDIT_READ", "PERFMON", "BPF", "CHECKPOINT_RESTORE",
]  # fmt: skip
HELPERS = re.compile(r"\b(sudo|su-exec|gosu|setpriv|runuser|chpst|entrypoint-demoter|chown|setcap)\b|\bsu\s+-?\s*\w")
CAPABILITY_XATTR = "SCHILY.xattr.security.capability"
SETUID_BIT = 0o4000
SETGID_BIT = 0o2000
EXECUTE_BITS = 0o111
MAX_SCRIPT_BYTES = 262144
MAX_HELPER_LINES = 15
# The xattr's first word is the revision plus the effective flag; v1 holds one
# 32-bit word per set, v2 and v3 hold two.
VFS_CAP_FLAGS_EFFECTIVE = 1
VFS_CAP_REVISION_MASK = 0xFF000000
VFS_CAP_REVISION_1 = 0x01000000

Files = dict[str, tuple[int, str | None, str | None]]


def decode_capability(raw: bytes) -> dict:
    """A `security.capability` xattr value as its capability names and effective bit."""
    magic = struct.unpack_from("<I", raw, 0)[0]
    words = 1 if magic & VFS_CAP_REVISION_MASK == VFS_CAP_REVISION_1 else 2
    permitted = inheritable = 0
    offset = 4
    for word in range(words):
        permitted_word, inheritable_word = struct.unpack_from("<II", raw, offset)
        permitted |= permitted_word << (32 * word)
        inheritable |= inheritable_word << (32 * word)
        offset += 8

    def names(mask: int) -> list[str]:
        return [name for number, name in enumerate(CAPABILITIES) if mask >> number & 1]

    return {"effective_bit": bool(magic & VFS_CAP_FLAGS_EFFECTIVE), "permitted": names(permitted), "inheritable": names(inheritable)}


def _path(member_name: str) -> str:
    return "/" + member_name.removeprefix("./").lstrip("/")


def collect_files(image_tar: Path) -> Files:
    """The regular files of the image's final filesystem: path -> (mode, capability xattr, script text).

    Layers apply in order, so a later layer's whiteout removes a lower layer's
    file and a later file replaces it.
    """
    files: Files = {}
    with tarfile.open(image_tar) as outer:
        manifest = json.load(outer.extractfile("manifest.json"))[0]
        for layer in manifest["Layers"]:
            with tarfile.open(fileobj=outer.extractfile(layer), mode="r|*") as members:
                for member in members:
                    name = _path(member.name)
                    base = PurePosixPath(name).name
                    parent = str(PurePosixPath(name).parent)
                    if base == ".wh..wh..opq":
                        for path in [path for path in files if path.startswith(parent.rstrip("/") + "/")]:
                            del files[path]
                    elif base.startswith(".wh."):
                        gone = str(PurePosixPath(parent) / base.removeprefix(".wh."))
                        for path in [path for path in files if path == gone or path.startswith(gone + "/")]:
                            del files[path]
                    elif not member.isfile():
                        files.pop(name, None)
                    else:
                        files[name] = (member.mode, member.pax_headers.get(CAPABILITY_XATTR), _script_text(members, member, name))
    return files


def _script_text(members: tarfile.TarFile, member: tarfile.TarInfo, name: str) -> str | None:
    if not (member.mode & EXECUTE_BITS or name.endswith(".sh")) or not 0 < member.size <= MAX_SCRIPT_BYTES:
        return None
    content = members.extractfile(member).read()
    return content.decode("utf-8", "replace") if content.startswith(b"#!") else None


def findings(image: str, config: dict, files: Files) -> dict:
    """What the image's config and filesystem say about privilege, in report order."""
    result = {
        "image": image,
        "user": config.get("User") or "root",
        "entrypoint": config.get("Entrypoint"),
        "cmd": config.get("Cmd"),
        "setuid": [],
        "setgid": [],
        "filecaps": [],
        "helpers": [],
    }
    for name, (mode, capability, script) in sorted(files.items()):
        if mode & SETUID_BIT:
            result["setuid"].append(name)
        if mode & SETGID_BIT:
            result["setgid"].append(name)
        if capability:
            result["filecaps"].append({"path": name, **decode_capability(capability.encode("utf-8", "surrogateescape"))})
        for number, line in enumerate((script or "").splitlines(), 1):
            if not line.lstrip().startswith("#") and HELPERS.search(line):
                result["helpers"].append(f"{name}:{number}: {line.strip()[:110]}")
    return result


def docker_config(image: str) -> dict:
    return json.loads(subprocess.check_output(["docker", "image", "inspect", image]))[0]["Config"]


def docker_save(image: str, destination: Path) -> None:
    subprocess.check_call(["docker", "save", "-o", str(destination), image])


def running_images() -> list[str]:
    return sorted(set(subprocess.check_output(["docker", "ps", "--format", "{{.Image}}"], text=True).split()))


def scan(image: str) -> dict:
    config = docker_config(image)
    with tempfile.TemporaryDirectory(prefix="scan.") as directory:
        archive = Path(directory) / "image.tar"
        docker_save(image, archive)
        return findings(image, config, collect_files(archive))


def report(result: dict) -> str:
    lines = [
        "",
        f"=== {result['image']}",
        f"  user={result['user']} entrypoint={result['entrypoint']} cmd={result['cmd']}",
        "  no-new-privileges blockers (setuid/setgid binaries): " + (", ".join(result["setuid"] + result["setgid"]) or "none"),
    ]
    if result["filecaps"]:
        lines += [
            f"  file capability: {cap['path']} permitted={cap['permitted']} effective_bit={cap['effective_bit']}  -> cap_drop ALL breaks it unless re-added"
            for cap in result["filecaps"]
        ]
    else:
        lines.append("  file capabilities: none")
    if result["helpers"]:
        lines.append("  privilege-drop / chown helpers in shell scripts:")
        lines += ["    " + helper for helper in result["helpers"][:MAX_HELPER_LINES]]
    else:
        lines.append("  privilege-drop / chown helpers in shell scripts: none found (a compiled entrypoint can still do it)")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    images = running_images() if argv == ["--running"] else argv
    failed = False
    for image in images:
        # One unreadable image must not hide the rest.
        try:
            print(report(scan(image)))
        except (subprocess.CalledProcessError, OSError, tarfile.TarError, KeyError, ValueError) as error:
            failed = True
            print(f"\n=== {image}\n  scan failed: {error}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
