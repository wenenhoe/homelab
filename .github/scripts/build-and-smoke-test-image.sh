#!/usr/bin/env bash
# Builds docker/<app>/Dockerfile without pushing it, then runs that app's
# smoke test against the result. Used by pr-checks.yml's
# dockerfile-build-check job — see docs/ci.md#dockerfile-changes.
#
# Every Dockerfile needs a .github/image-smoke-tests/<app>.sh: a new one
# without it fails here rather than being built and never exercised.
#
# Usage: build-and-smoke-test-image.sh <app>
set -euo pipefail

app="$1"
smoke=".github/image-smoke-tests/$app.sh"

if [ ! -f "$smoke" ]; then
  echo "::error::docker/$app has a Dockerfile but $smoke doesn't exist; add a smoke test for the image."
  exit 1
fi

image="local/$app:pr-check"
docker build --tag "$image" "docker/$app"
bash "$smoke" "$image"
