#!/usr/bin/env bash
# Downloads the OPNsense image from URL to BZ2, checks it against the published
# SHA-256 in SUM, and only then unpacks it next to it. A mismatch removes the
# download and leaves no unpacked image behind.
set -euo pipefail

mkdir -p "$(dirname "$BZ2")"
curl -fL --retry 3 -o "$BZ2" "$URL"

# macOS has shasum, not sha256sum.
got=$( (sha256sum "$BZ2" 2> /dev/null || shasum -a 256 "$BZ2") | cut -d' ' -f1)
if [ "$got" != "$SUM" ]; then
  rm -f "$BZ2"
  echo "checksum mismatch for $URL: expected $SUM, downloaded $got" >&2
  exit 1
fi

bunzip2 -kf "$BZ2"
