#!/usr/bin/env python3
"""Building this checkout's Dockerfiles in CI: for a boot test, and to check them.

The images built from docker/<app>/Dockerfile are only published after
merge, so a PR's own Dockerfile change is otherwise never exercised — see
docs/topics/engineering/ci.md#dockerfile-changes.

`shadow-tag` builds an app's Dockerfile and tags the result as the
`ghcr.io/wenenhoe/<image>` reference its deployed compose file pins, so
`docker compose up` runs it instead of pulling the published one (compose's
default pull_policy, `missing`, uses a local image when the tag exists).
The image name comes from ci.images.registry; the tag is whatever the
compose file pins, which `check-pins` separately holds equal to the
published one. An app with no Dockerfile, or a compose file pinning none of
its image, is left alone; a Dockerfile with no registry entry is an error.

`build-check` builds it as local/<app>:pr-check without pushing, then runs
.github/image-smoke-tests/<app>.sh against the result. Every Dockerfile
needs a smoke test: a new one without it fails here instead of being built
and never exercised.

Subcommands (from tools/: python -m ci.images.build ...):
  shadow-tag <app> <deployed-compose-file>
  build-check <app>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ci.images.registry import REGISTRY, ImageError, lookup
from ci.proc import Runner, run

REPO_ROOT = Path(__file__).resolve().parents[3]
SMOKE_DIR = ".github/image-smoke-tests"


def shadow_tag(root: Path, app: str, compose_file: str, runner: Runner = run) -> int:
    if not (root / "docker" / app / "Dockerfile").is_file():
        print(f"docker/{app} has no Dockerfile; using published images.")
        return 0
    image = lookup(app)
    listing = runner(["docker", "compose", "-f", compose_file, "config", "--images"], root, True)
    if listing.returncode != 0:
        print(f"::error::docker compose config --images failed for {compose_file}")
        return listing.returncode
    prefix = f"{REGISTRY}/{image.name}:"
    pinned = sorted({line.strip() for line in listing.stdout.splitlines() if line.strip().startswith(prefix)})
    if not pinned:
        print(f"::notice::docker/{app} has a Dockerfile but {compose_file} pins no {prefix}* image; nothing to shadow.")
        return 0
    print(f"Building {image.context}/Dockerfile as {', '.join(pinned)}")
    tags = [arg for ref in pinned for arg in ("--tag", ref)]
    return runner(["docker", "build", *tags, image.context], root, False).returncode


def build_check(root: Path, app: str, runner: Runner = run) -> int:
    image = lookup(app)
    smoke = f"{SMOKE_DIR}/{app}.sh"
    if not (root / smoke).is_file():
        print(f"::error::{image.context}/Dockerfile exists but {smoke} doesn't; add a smoke test for the image.")
        return 1
    local = f"local/{app}:pr-check"
    code = runner(["docker", "build", "--tag", local, image.context], root, False).returncode
    if code != 0:
        return code
    return runner(["bash", smoke, local], root, False).returncode


def main(argv: list[str] | None = None, runner: Runner = run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    shadow = sub.add_parser("shadow-tag")
    shadow.add_argument("app")
    shadow.add_argument("compose_file")
    check = sub.add_parser("build-check")
    check.add_argument("app")
    args = parser.parse_args(argv)
    try:
        if args.command == "shadow-tag":
            return shadow_tag(REPO_ROOT, args.app, args.compose_file, runner)
        return build_check(REPO_ROOT, args.app, runner)
    except ImageError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
