#!/bin/bash
# Restore the Minecraft world from a backup tarball.
#
# Runs the `restore-backup` service from compose.restore.yaml: an ephemeral
# itzg/mc-backup container (`restore-tar-backup` entrypoint) that reads from
# ./backups (produced nightly by the `backups` service in compose.yaml,
# 4am cron) and writes into ./data — the same bind mount the `mc` service
# uses, so the `mc` container should be stopped before running this to
# avoid restoring into a live world.
#
# Usage: ./run_restore.sh
# Which backup gets restored, and any other restore options, are controlled
# by mc-backup's own env vars — see compose.restore.yaml / the itzg/mc-backup
# image docs if non-default behavior is needed.
set -e

echo "Starting Minecraft restore..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT" || exit 1

docker compose \
  -f compose.restore.yaml \
  run --rm restore-backup
