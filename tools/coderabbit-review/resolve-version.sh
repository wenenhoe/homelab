#!/usr/bin/env bash
# Prints the CLI version the Dockerfile pins, and fails unless it declares
# exactly one `ARG CODERABBIT_VERSION=X.Y.Z`. Both CI jobs call this so a
# malformed or duplicated ARG is rejected the same way in a PR as on main,
# before the value can reach an image tag.
set -euo pipefail

dockerfile="$(dirname "${BASH_SOURCE[0]}")/Dockerfile"
line="$(grep -E '^ARG CODERABBIT_VERSION=' "$dockerfile" || true)"

if [ "$(printf '%s\n' "$line" | wc -l)" -ne 1 ] \
    || ! printf '%s' "$line" | grep -Eq '^ARG CODERABBIT_VERSION=[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "Expected exactly one 'ARG CODERABBIT_VERSION=X.Y.Z' in $dockerfile, got: '$line'" >&2
  exit 1
fi

echo "${line#ARG CODERABBIT_VERSION=}"
