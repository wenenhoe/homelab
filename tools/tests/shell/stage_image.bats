#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tofu/scratch/opnsense/stage_image.sh)
  STORE="$BATS_TEST_TMPDIR/store"
  TARGET="$STORE/import/OPNsense-26.1.6-nano-amd64.raw"
  URL=https://mirror.example.net/releases/26.1/OPNsense-26.1.6-nano-amd64.img.bz2
  printf 'BZ2DATA\n' > "$BATS_TEST_TMPDIR/served.bz2"
  SUM=$(sha256sum "$BATS_TEST_TMPDIR/served.bz2" | cut -d' ' -f1)
  export SERVED="$BATS_TEST_TMPDIR/served.bz2"
  # curl writes the file named after -o; bunzip2 -c prints the unpacked image.
  stub curl <<'BODY'
while [ "$#" -gt 0 ]; do
  [ "$1" = -o ] && cp "$SERVED" "$2"
  shift
done
BODY
  stub bunzip2 <<'BODY'
printf 'RAWIMAGE\n'
BODY
}

teardown() {
  harness_teardown
}

@test "stages the unpacked image under the target name and records the checksum beside it" {
  run -0 "$SCRIPT" "$URL" "$SUM" "$TARGET"

  [ "$(cat "$TARGET")" = RAWIMAGE ]
  [ "$(cat "$TARGET.sha256")" = "$SUM" ]
  run calls_to curl
  assert_output --partial "-fL --retry 3 -o"
  assert_output --partial "$URL"
}

@test "leaves no temporary file in the datastore or in its import directory" {
  run -0 "$SCRIPT" "$URL" "$SUM" "$TARGET"

  run ls -A "$STORE"
  assert_output "import"
  run ls -A "$STORE/import"
  assert_output --regexp '^OPNsense-26.1.6-nano-amd64.raw
OPNsense-26.1.6-nano-amd64.raw.sha256$'
}

@test "a checksum mismatch fails, keeps an image already staged and leaves nothing behind" {
  mkdir -p "$STORE/import"
  printf 'OLD\n' > "$TARGET"

  run -1 "$SCRIPT" "$URL" "$(printf '1%.0s' $(seq 64))" "$TARGET"

  assert_output --partial "checksum mismatch for $URL"
  [ "$(cat "$TARGET")" = OLD ]
  [ ! -e "$TARGET.sha256" ]
  run ls -A "$STORE"
  assert_output "import"
}

@test "an unpack that fails leaves the target as it was" {
  stub bunzip2 <<'BODY'
exit 2
BODY

  run -2 "$SCRIPT" "$URL" "$SUM" "$TARGET"

  [ ! -e "$TARGET" ]
  run ls -A "$STORE"
  assert_output "import"
}

@test "refuses to start when the datastore has too little room" {
  MIN_FREE_KB=999999999999 run -1 "$SCRIPT" "$URL" "$SUM" "$TARGET"

  assert_output --partial "less than 4.5 GB free"
  run calls_to curl
  assert_output ""
}

@test "replaces an older staged image of the same name" {
  mkdir -p "$STORE/import"
  printf 'OLD\n' > "$TARGET"
  printf 'old-sum\n' > "$TARGET.sha256"

  run -0 "$SCRIPT" "$URL" "$SUM" "$TARGET"

  [ "$(cat "$TARGET")" = RAWIMAGE ]
  [ "$(cat "$TARGET.sha256")" = "$SUM" ]
}
