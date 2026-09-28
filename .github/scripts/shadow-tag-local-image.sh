#!/usr/bin/env bash
# Builds docker/<app>/Dockerfile and tags the result as the ghcr.io image
# the app's compose file pins, so `docker compose up` runs this checkout's
# Dockerfile instead of pulling the published one. Compose's default
# pull_policy (missing) uses a local image when the tag already exists.
#
# The published image is only built after merge, so without this a
# Dockerfile edit that keeps the same tag boots the old image, and a
# Dockerfile bump boots nothing (the new tag isn't in ghcr yet) — see
# docs/ci.md#dockerfile-changes.
#
# The image reference is read from the deployed compose file
# (`docker compose config --images`), not hard-coded per app. An app with
# no Dockerfile is left alone, and so is one whose compose file pins no
# ghcr.io/wenenhoe image. More than one such image is ambiguous: which
# one the Dockerfile produces can't be derived, so it fails.
#
# Usage: shadow-tag-local-image.sh <app> <deployed-compose-file>
set -euo pipefail

app="$1"
compose_file="$2"

if [ ! -f "docker/$app/Dockerfile" ]; then
  echo "docker/$app has no Dockerfile; using published images."
  exit 0
fi

refs=$(docker compose -f "$compose_file" config --images | grep -E '^ghcr\.io/wenenhoe/' | sort -u || true)
count=$(printf '%s\n' "$refs" | grep -c . || true)

if [ "$count" -eq 0 ]; then
  echo "::notice::docker/$app has a Dockerfile but $compose_file pins no ghcr.io/wenenhoe image; nothing to shadow."
  exit 0
fi
if [ "$count" -gt 1 ]; then
  printf '::error::%s pins %s ghcr.io/wenenhoe images and only one Dockerfile builds; cannot tell which to shadow:\n%s\n' "$compose_file" "$count" "$refs"
  exit 1
fi

echo "Building docker/$app/Dockerfile as $refs"
docker build --tag "$refs" "docker/$app"
