#!/usr/bin/env bash
# Build seed.img for the module's seed_image_path: an MBR disk with one FAT
# partition holding conf/config.xml, the layout opnsense-importer mounts as
# /dev/<disk>s1 (msdos).
# Usage: build_seed.sh OUTPUT_DIR --lan-ip ADDRESS [patch_config.py options]
# Needs: python3, openssl, sfdisk, mtools (mformat, mmd, mcopy, mdir), xmllint, truncate.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
out=${1:?usage: build_seed.sh OUTPUT_DIR --lan-ip ADDRESS [patch_config.py options]}
shift
umask 077
mkdir -p "$out"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

python3 -I "$here/patch_config.py" --out "$work/config.xml" "$@"
xmllint --noout "$work/config.xml"

img="$out/seed.img"
size_mib=64
offset=$((2048 * 512))
rm -f "$img"
truncate -s "${size_mib}M" "$img"
# The partition starts at 1 MiB, runs to the end of the disk and has type 0x0e
# (FAT16 LBA), which is what mformat makes at this size.
echo 'start=2048, type=e' | sfdisk --quiet "$img"
sectors=$(((size_mib * 1024 * 1024 - offset) / 512))
mformat -i "$img@@$offset" -T "$sectors" -h 64 -s 32 -v SEED ::
mmd -i "$img@@$offset" ::/conf
mcopy -i "$img@@$offset" "$work/config.xml" ::/conf/config.xml

mdir -i "$img@@$offset" -/ ::
echo "seed: $img"
