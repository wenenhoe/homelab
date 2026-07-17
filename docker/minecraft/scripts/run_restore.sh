#!/bin/bash
set -e

echo "Starting Minecraft restore..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT" || exit 1

docker compose \
  -f compose.restore.yaml \
  run --rm restore-backup
