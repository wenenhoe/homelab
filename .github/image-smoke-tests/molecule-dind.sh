#!/usr/bin/env bash
# Smoke test for docker/molecule-dind/Dockerfile: what it pre-bakes so
# Molecule scenarios skip installing it — Docker Engine, python3-requests,
# fuse-overlayfs, and the fuse-overlayfs daemon.json default. The image's
# own default command is systemd, so the entrypoint is overridden.
# Usage: molecule-dind.sh <image>
set -euo pipefail

docker run --rm --entrypoint sh "$1" -c '
  set -e
  docker --version
  dockerd --version
  python3 -c "import requests"
  command -v fuse-overlayfs
  grep -q fuse-overlayfs /etc/docker/daemon.json
'
