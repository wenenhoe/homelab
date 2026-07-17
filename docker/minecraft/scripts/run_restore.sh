#!/usr/bin/env bash
set -e

echo "Starting Minecraft restore..."

docker compose \
  -f compose.restore.yaml \
  run --rm restore-backup
