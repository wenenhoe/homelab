#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tofu/modules/proxmox_opnsense_vm/fetch_image.sh)
  CACHE="$BATS_TEST_TMPDIR/cache/nested"
  export URL=https://mirror.example.net/OPNsense-26.1-nano-amd64.img.bz2
  export BZ2="$CACHE/OPNsense-26.1-nano-amd64.img.bz2"
  IMG="$CACHE/OPNsense-26.1-nano-amd64.img"
  # The "download" writes a real bzip2 file of a known image to the -o path, as
  # curl would; CURL_FAIL makes it fail with curl's HTTP error status.
  stub curl <<'BODY'
[ -z "${CURL_FAIL:-}" ] || exit 22
while [ "$#" -gt 0 ]; do
  [ "$1" = -o ] && printf 'raw image bytes\n' | bzip2 > "$2"
  shift
done
BODY
  SUM=$(printf 'raw image bytes\n' | bzip2 | sha256sum | cut -d' ' -f1)
  export SUM
}

teardown() {
  harness_teardown
}

@test "a download that matches the published checksum is unpacked next to it" {
  run -0 "$SCRIPT"
  assert_equal "$(cat "$IMG")" "raw image bytes"
  [ -f "$BZ2" ]
}

@test "the download is a plain curl of the URL into the cache directory" {
  run -0 "$SCRIPT"
  run calls_to curl
  assert_output "curl -fL --retry 3 -o $BZ2 $URL"
}

@test "a download that does not match is removed and nothing is unpacked" {
  SUM=0000000000000000000000000000000000000000000000000000000000000000
  export SUM
  run -1 "$SCRIPT"
  assert_output --partial "checksum mismatch for $URL: expected $SUM"
  [ ! -e "$IMG" ]
  [ ! -e "$BZ2" ]
}

@test "a failed download stops before anything is checked or unpacked" {
  CURL_FAIL=1 run -22 "$SCRIPT"
  [ ! -e "$IMG" ]
}
