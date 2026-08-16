#!/bin/bash
# Restore the Minecraft world from the on-host backup tarball.
#
# Stops the live stack (compose.yaml), runs the `restore-backup` service
# from compose.restore.yaml — an ephemeral itzg/mc-backup container
# (`restore-tar-backup` entrypoint) that unpacks the newest tar in
# ./backups (produced nightly by the `backups` service, 4am cron) into
# ./data, the same volume `mc` uses — then brings the stack back up.
# Stopping first isn't optional: restoring into a live world's files
# risks a corrupt/partial write.
#
# This restores from whatever's already in ./backups. If that volume
# itself needs reconstituting from an offsite archive first (host disk
# loss, not an ordinary rollback), run playbooks/restore.yaml
# (restore_app=minecraft, restore_volumes=["minecraft_backups"]) before
# this script — see docs/disaster-recovery.md.
#
# Usage: ./run_restore.sh [-y|--yes]
#   -y, --yes   skip the confirmation prompt (for non-interactive use)
# Which backup gets restored, and any other restore options, are
# controlled by mc-backup's own env vars — see compose.restore.yaml /
# the itzg/mc-backup image docs if non-default behavior is needed.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT" || exit 1

CONFIRMED=false
for arg in "$@"; do
  case "$arg" in
    -y|--yes) CONFIRMED=true ;;
  esac
done

if [ "$CONFIRMED" != true ]; then
  read -r -p "This will STOP minecraft and overwrite minecraft_data with the newest backup. Type 'yes' to continue: " REPLY
  if [ "$REPLY" != "yes" ]; then
    echo "Restore aborted — confirmation not given."
    exit 1
  fi
fi

# Whatever happens below, always try to leave the stack running rather
# than stopped — a failed restore attempt shouldn't also mean downtime.
restart_stack() {
  echo "Bringing the minecraft stack back up..."
  docker compose -f compose.yaml up -d
}
trap restart_stack EXIT

echo "Stopping the minecraft stack..."
docker compose -f compose.yaml stop

echo "Starting Minecraft restore..."
docker compose \
  -f compose.restore.yaml \
  run --rm restore-backup
