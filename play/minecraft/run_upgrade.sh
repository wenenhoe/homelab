#!/usr/bin/env bash
set -e

# Use the first argument passed to the script, or default to 26.1.2 if empty
VERSION="${1:-26.1.2}"

echo "Starting test-upgrade with VERSION=${VERSION}..."

sudo VERSION="$VERSION" docker compose \
  -f compose.yaml \
  -f compose.upgrade.yaml \
  run --rm test-upgrade

