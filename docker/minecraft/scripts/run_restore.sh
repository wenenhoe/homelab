#!/bin/bash
# Restore the Minecraft world from the on-host backup tarball.
#
# Checks that the newest tar in ./backups reads cleanly, asks for a second
# confirmation, then stops the live stack (compose.yaml), deletes everything
# in ./data (the volume `mc` uses), runs the `restore-backup` service from
# compose.restore.yaml — an ephemeral itzg/mc-backup container
# (`restore-tar-backup` entrypoint) that unpacks the newest tar in ./backups
# (produced nightly by the `backups` service, 4am cron) into the now-empty
# ./data — and brings the stack back up. The delete is what makes this a
# rollback: restore-tar-backup extracts only into an empty directory.
# Stopping first isn't optional: restoring into a live world's files
# risks a corrupt/partial write.
#
# If the restore fails after ./data was emptied, the stack is left stopped.
# Starting it would generate a fresh world, and the nightly backup would
# then rotate the good archives out. Fix the cause and run this again.
#
# This restores from whatever's already in ./backups. If that volume
# itself needs reconstituting from a backup archive first (host disk
# loss, not an ordinary rollback), run playbooks/restore.yaml
# (restore_app=minecraft, restore_volumes=["minecraft_backups"]) before
# this script — see docs/topics/disaster-recovery/backup.md.
#
# Usage: ./run_restore.sh [-y|--yes]
#   -y, --yes   skip both confirmation prompts (for non-interactive use)
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

# These run in the restore image, so they see the volumes the restore will.
read -r -d '' PREFLIGHT <<'SCRIPT' || true
newest=$(ls -t /backups | head -1)
[ -n "$newest" ] || { echo "minecraft_backups holds no backup to restore." >&2; exit 1; }
tar tf "/backups/$newest" > /dev/null || { echo "$newest cannot be read as a tar archive." >&2; exit 1; }
set -- $(du -sh "/backups/$newest"); echo "Newest backup: $newest ($1)"
set -- $(du -sh /data); echo "minecraft_data now holds $1 in $(find /data -mindepth 1 | wc -l) files and directories."
SCRIPT
read -r -d '' WIPE <<'SCRIPT' || true
find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
[ -z "$(ls -A /data)" ]
SCRIPT
read -r -d '' NOT_EMPTY <<'SCRIPT' || true
[ -n "$(ls -A /data)" ]
SCRIPT

# Only the entrypoint changes: the service keeps its capabilities and network
# mode. -T and </dev/null keep the container from reading the prompts' stdin.
restore_sh() {
  docker --log-level ERROR compose -f compose.restore.yaml \
    run --rm -T --entrypoint sh restore-backup -c "$1" < /dev/null
}

echo "Checking the newest backup..."
restore_sh "$PREFLIGHT"

if [ "$CONFIRMED" != true ]; then
  read -r -p "This will DELETE everything in minecraft_data and restore it from that backup. Type 'delete' to continue: " REPLY
  if [ "$REPLY" != "delete" ]; then
    echo "Restore aborted — nothing was stopped or deleted."
    exit 1
  fi
fi

WIPED=false
RESTORED=false

# Whatever happens below, try to leave the stack running rather than
# stopped — a failed restore attempt shouldn't also mean downtime. The one
# exception is a failure after minecraft_data was emptied (see the header).
restart_stack() {
  if [ "$WIPED" = true ] && [ "$RESTORED" != true ]; then
    echo "The restore did not finish after minecraft_data was emptied or partly deleted, so the stack is NOT being started." >&2
    echo "Fix the cause and run this script again." >&2
    return
  fi
  echo "Bringing the minecraft stack back up..."
  docker compose -f compose.yaml up -d
}
trap restart_stack EXIT

echo "Stopping the minecraft stack..."
docker compose -f compose.yaml stop

echo "Emptying minecraft_data..."
WIPED=true
restore_sh "$WIPE"

echo "Starting Minecraft restore..."
docker compose \
  -f compose.restore.yaml \
  run --rm restore-backup

# restore-tar-backup exits 0 without extracting when it finds no backup.
restore_sh "$NOT_EMPTY"
RESTORED=true
