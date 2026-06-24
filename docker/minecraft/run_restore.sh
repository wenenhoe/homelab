#!/usr/bin/env bash
set -e

echo "Starting Minecraft restore..."

sudo docker compose \
  -f compose.restore.yaml \
  run --rm restore-backup
