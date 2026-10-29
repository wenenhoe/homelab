#!/usr/bin/env bash
# Runs on the Proxmox node, piped in by scratch_gateway.sh: bash -s -- URL SHA256 TARGET.
# Downloads the OPNsense image, checks it against the published SHA-256, unpacks it and moves it
# to TARGET (a .raw file in a datastore's import directory) in one rename, then writes the
# checksum beside it so a later run can tell the file is the one it wants. A failure at any
# step leaves TARGET as it was and no temporary files behind.
set -euo pipefail

url=$1
sum=$2
target=$3
dir=$(dirname "$target")

mkdir -p "$dir"
# Under the datastore's root, not in import/, so the rename stays on one filesystem and a stray
# temporary file is never offered as import content.
work=$(mktemp -d "$(dirname "$dir")/.stage.XXXXXX")
trap 'rm -rf "$work"' EXIT

free_kb=$(df -Pk "$work" | awk 'NR==2 {print $4}')
[ "$free_kb" -ge "${MIN_FREE_KB:-4500000}" ] || {
  echo "less than 4.5 GB free where the image is stored" >&2
  exit 1
}

curl -fL --retry 3 -o "$work/image.bz2" "$url"
got=$(sha256sum "$work/image.bz2" | cut -d' ' -f1)
if [ "$got" != "$sum" ]; then
  echo "checksum mismatch for $url: expected $sum, downloaded $got" >&2
  exit 1
fi

bunzip2 -c "$work/image.bz2" > "$work/image.raw"
mv "$work/image.raw" "$target"
printf '%s\n' "$sum" > "$target.sha256"
