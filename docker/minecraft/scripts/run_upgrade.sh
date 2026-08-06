#!/bin/bash
# Dry-run a Minecraft server version bump before touching the live server.
#
# Runs the `test-upgrade` service from compose.upgrade.yaml: an ephemeral
# itzg/minecraft-server container with SETUP_ONLY=true and the candidate
# VERSION, which downloads that server jar plus every mod in
# configs/modrinth-mods.txt and validates Fabric/Modrinth dependency
# resolution, then exits — no world data touched, nothing left running.
#
# Usage: ./run_upgrade.sh [version]   (defaults to 26.1.2 if omitted)
# A clean exit means it's safe to bump `VERSION` in compose.yaml's `mc`
# service and redeploy for real.
set -e

handle_exit_signal() {
  STATUS=$?
  if [ $STATUS -eq 0 ]; then
    echo "Upgrade is successful."
  else
    echo "Upgrade failed with exit code: $STATUS"
  fi
}
trap handle_exit_signal EXIT

VERSION="${1:-26.1.2}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT" || exit 1

echo "Starting test-upgrade with VERSION=${VERSION}..."

# --log-level ERROR hides the orphan container warning
VERSION="$VERSION" docker --log-level ERROR compose \
  -f compose.upgrade.yaml \
  run --rm test-upgrade
