#!/usr/bin/env bash
# docker/wastebin's image is booted and health-checked for real by
# compose-boot-test, against this same Dockerfile (shadow-tagged — see
# tools/ci/images/build.py), so this only confirms the
# build produced an image. Usage: wastebin.sh <image>
set -euo pipefail

docker image inspect "$1" > /dev/null
