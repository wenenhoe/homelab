#!/usr/bin/env python3
"""Copy the backup bucket from one S3 endpoint to the local SeaweedFS and prove the copy is whole.

Runs as root on the rebuilt `storage` host, piped over SSH:
    ssh storage 'sudo python3 - [--pin ADDRESS] [--from NAME] [--bucket NAME] [--check-only]' < tools/rebuild_check/scripts/bucket_copy.py

The source is a remote of the deployed cloud-sync `rclone.conf` (`seaweedfs`, the reader at the name every
client uses, unless --from names a cloud target). The destination is this host's SeaweedFS, reached on the
`caddy-proxy` network past Caddy and DNS with the admin identity read out of the running container. Nothing is
typed or pasted: the credentials come from what the deploy already put on the host, are handed to rclone in a
0600 env file that is removed when the run ends, and are never printed.

--pin ADDRESS makes the source's name resolve to ADDRESS inside the copy. After DNS has moved that name to this
host it would otherwise name the destination, and every check would compare a server with itself.

The copy is `rclone copy --immutable`, so a repeat adds only what arrived since the last pass. The check is
`rclone check --size-only`, since an object written in parts may not keep its ETag. It exits non-zero when the
sides differ. The image is the one `cloud-sync.service` runs, read from its unit file.
"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

DEPLOY_DIR = Path("/opt/stacks")
RCLONE_CONF = DEPLOY_DIR / "cloud-sync/rclone.conf"
SERVICE_UNIT = Path("/etc/systemd/system/cloud-sync.service")
IDENTITY_IN_CONTAINER = "/etc/seaweedfs/s3-identity.json"
ADMIN_IDENTITY = "seaweedfs-bucket-admin"
LOCAL_ENDPOINT = "http://seaweedfs:8333"
NETWORK = "caddy-proxy"
IMAGE_RE = re.compile(r"rclone/rclone:\S+@sha256:[0-9a-f]{64}")

Run = Callable[..., subprocess.CompletedProcess]


class CopyError(Exception):
    """Something the copy cannot go on without; the message says what to look at."""


def cloud_sync_image(unit_text: str) -> str:
    match = IMAGE_RE.search(unit_text)
    if match is None:
        raise CopyError(f"no pinned rclone image in {SERVICE_UNIT}: deploy cloud_sync to this host first")
    return match.group(0)


def source_remote(conf_text: str, section: str) -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(conf_text)
    if not parser.has_section(section):
        raise CopyError(f"no [{section}] in {RCLONE_CONF}; it has: {', '.join(parser.sections())}")
    remote = dict(parser[section])
    for key in ("access_key_id", "secret_access_key", "endpoint"):
        if not remote.get(key):
            raise CopyError(f"[{section}] in {RCLONE_CONF} has no {key}")
    return remote


def admin_remote(identity_json: str) -> dict[str, str]:
    try:
        identities = json.loads(identity_json)["identities"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CopyError(f"{IDENTITY_IN_CONTAINER} in the seaweedfs container is not an identity file ({exc})") from exc
    for identity in identities:
        if identity.get("name") == ADMIN_IDENTITY and identity.get("credentials"):
            credentials = identity["credentials"][0]
            return {"access_key_id": credentials["accessKey"], "secret_access_key": credentials["secretKey"], "endpoint": LOCAL_ENDPOINT}
    raise CopyError(f"no {ADMIN_IDENTITY} with a credential in {IDENTITY_IN_CONTAINER}")


def remote_env(name: str, remote: dict[str, str]) -> dict[str, str]:
    """rclone's env-var form of one remote: S3 on a provider that is neither AWS nor a known vendor, path-style."""
    prefix = f"RCLONE_CONFIG_{name.upper()}_"
    env = {
        f"{prefix}TYPE": "s3",
        f"{prefix}PROVIDER": "Other",
        f"{prefix}FORCE_PATH_STYLE": "true",
        f"{prefix}ACCESS_KEY_ID": remote["access_key_id"],
        f"{prefix}SECRET_ACCESS_KEY": remote["secret_access_key"],
        f"{prefix}ENDPOINT": remote["endpoint"],
    }
    if remote.get("region"):
        env[f"{prefix}REGION"] = remote["region"]
    return env


def write_env_file(env: dict[str, str]) -> Path:
    descriptor, name = tempfile.mkstemp(prefix="bucket-copy-", suffix=".env")
    with os.fdopen(descriptor, "w") as handle:
        handle.write("".join(f"{key}={value}\n" for key, value in env.items()))
    return Path(name)


def pin_argument(endpoint: str, address: str) -> list[str]:
    host = urlsplit(endpoint).hostname
    if not host or re.fullmatch(r"[0-9.]+", host):
        raise CopyError(f"--pin needs a source endpoint with a name, not {endpoint!r}: an address is not resolved")
    return ["--add-host", f"{host}:{address}"]


def docker_argv(image: str, env_file: Path, pin: list[str], rclone_args: Sequence[str]) -> list[str]:
    return [
        "docker", "run", "--rm", "--network", NETWORK, "--env-file", str(env_file), *pin,
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--read-only",
        image, "--config", "/dev/null", *rclone_args,
    ]  # fmt: skip


def run_copy(args: argparse.Namespace, run: Run) -> int:
    image = cloud_sync_image(SERVICE_UNIT.read_text())
    source = source_remote(RCLONE_CONF.read_text(), args.source)
    identity = run(["docker", "exec", "seaweedfs", "cat", IDENTITY_IN_CONTAINER], capture_output=True, text=True, check=False)
    if identity.returncode != 0:
        raise CopyError("could not read the identity file from the seaweedfs container: is it running?")
    destination = admin_remote(identity.stdout)
    pin = pin_argument(source["endpoint"], args.pin) if args.pin else []
    old, new = f"old:{args.bucket}", f"new:{args.bucket}"
    steps = [] if args.check_only else [("copy", ["copy", "--immutable", "--stats-one-line", "-v", old, new])]
    steps += [("size of the source", ["size", old]), ("size of the copy", ["size", new]), ("check", ["check", "--size-only", old, new])]
    env_file = write_env_file({**remote_env("old", source), **remote_env("new", destination)})
    try:
        for label, rclone_args in steps:
            print(f"--- {label}: rclone {' '.join(rclone_args)}", flush=True)
            result = run(docker_argv(image, env_file, pin, rclone_args), check=False)
            if result.returncode != 0:
                print(f"--- {label} failed (exit {result.returncode})", file=sys.stderr)
                return result.returncode
    finally:
        with contextlib.suppress(FileNotFoundError):
            env_file.unlink()
    print("--- the copy and the source hold the same files")
    return 0


def main(argv: list[str] | None = None, run: Run = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--from", dest="source", default="seaweedfs", help="remote of the cloud-sync rclone.conf to copy from")
    parser.add_argument("--bucket", default="homelab-backups")
    parser.add_argument("--pin", metavar="ADDRESS", help="make the source's name resolve to ADDRESS inside the copy")
    parser.add_argument("--check-only", action="store_true", help="compare only; copy nothing")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return run_copy(args, run)
    except CopyError as exc:
        print(f"bucket_copy: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
