#!/usr/bin/env bash
# Determines which apps' Dockerfiles pr-checks.yml's dockerfile-build-check
# job should build, given a base and head SHA to diff. Same shape as
# detect-changed-compose-apps.sh, and pulled out of detect-changes' `run:`
# block for the same reason.
#
# An app is queued when docker/<app>/Dockerfile itself changes. The image
# each Dockerfile publishes is only built after merge
# (.github/workflows/build-*-image.yml), so this is the one place a broken
# Dockerfile is caught before it lands — see docs/ci.md#dockerfile-changes.
#
# Usage: detect-changed-dockerfiles.sh <base-sha> <head-sha>
# Writes dockerfiles=<json array> to $GITHUB_OUTPUT.
set -euo pipefail

base="$1"
head="$2"
changed=$(git diff --name-only "$base" "$head")

# -f drops deleted Dockerfiles (git diff lists them too).
apps=()
while IFS= read -r app; do
  [ -f "docker/$app/Dockerfile" ] || continue
  apps+=("$app")
done < <(echo "$changed" \
  | grep -E '^docker/[^/]+/Dockerfile$' \
  | cut -d/ -f2 \
  | sort -u)

json=$(printf '%s\n' "${apps[@]:-}" | jq -R . | jq -sc 'map(select(length > 0))')
echo "dockerfiles=$json" >> "$GITHUB_OUTPUT"
echo "Building Dockerfiles: $json"
