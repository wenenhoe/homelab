#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tofu/modules/proxmox_opnsense_vm/seed/build_seed.sh)
  OUT="$BATS_TEST_TMPDIR/out"
  # The builder writes the --out file it is given, as the real one does.
  stub python3 <<'BODY'
[ -z "${PATCH_FAIL:-}" ] || exit 3
while [ "$#" -gt 0 ]; do
  [ "$1" = --out ] && printf '<opnsense/>\n' > "$2"
  shift
done
BODY
  stub xmllint <<'BODY'
[ -z "${BAD_XML:-}" ] || exit 1
BODY
  stub sfdisk <<'BODY'
cat > "$BATS_TEST_TMPDIR/sfdisk.stdin"
BODY
  stub mformat <<'BODY'
BODY
  stub mmd <<'BODY'
BODY
  stub mcopy <<'BODY'
BODY
  stub mdir <<'BODY'
BODY
}

teardown() {
  harness_teardown
}

@test "the options after the output directory go to the config builder" {
  run -0 "$SCRIPT" "$OUT" --lan-ip 192.168.77.1 --domain lab.internal
  run calls_to python3
  assert_output --regexp "^python3 -I .*/patch_config\.py --out .*/config\.xml --lan-ip 192\.168\.77\.1 --domain lab\.internal$"
}

@test "a call with no output directory is refused before anything is built" {
  run -1 "$SCRIPT"
  assert_output --partial "usage: build_seed.sh"
  [ -z "$(calls_to python3)" ]
}

@test "the disk has one FAT16 partition from 1 MiB, formatted to the end of the disk" {
  run -0 "$SCRIPT" "$OUT" --lan-ip 192.168.77.1
  assert_equal "$(cat "$BATS_TEST_TMPDIR/sfdisk.stdin")" "start=2048, type=e"
  run calls_to mformat
  assert_output "mformat -i $OUT/seed.img@@1048576 -T 129024 -h 64 -s 32 -v SEED ::"
  assert_equal "$(stat -c %s "$OUT/seed.img")" 67108864
}

@test "config.xml is copied to conf/config.xml on the partition" {
  run -0 "$SCRIPT" "$OUT" --lan-ip 192.168.77.1
  run calls_to mmd
  assert_output "mmd -i $OUT/seed.img@@1048576 ::/conf"
  run calls_to mcopy
  assert_output --regexp "^mcopy -i $OUT/seed\.img@@1048576 .*/config\.xml ::/conf/config\.xml$"
}

@test "the seed image holds the only copy of the configuration afterwards" {
  run -0 "$SCRIPT" "$OUT" --lan-ip 192.168.77.1
  source_path=$(calls_to mcopy | awk '{print $4}')
  [ -n "$source_path" ]
  [ ! -e "$source_path" ]
  [ -f "$OUT/seed.img" ]
}

@test "the seed is readable by its owner only" {
  run -0 "$SCRIPT" "$OUT" --lan-ip 192.168.77.1
  assert_equal "$(stat -c %a "$OUT" "$OUT/seed.img")" "$(printf '700\n600')"
}

@test "a config builder that fails stops before an image is made and keeps the earlier seed" {
  mkdir -p "$OUT"
  printf 'earlier seed' > "$OUT/seed.img"
  PATCH_FAIL=1 run -3 "$SCRIPT" "$OUT" --lan-ip 192.168.77.1
  assert_equal "$(cat "$OUT/seed.img")" "earlier seed"
  [ -z "$(calls_to mformat)" ]
}

@test "a configuration that is not well-formed XML stops before an image is made" {
  mkdir -p "$OUT"
  printf 'earlier seed' > "$OUT/seed.img"
  BAD_XML=1 run -1 "$SCRIPT" "$OUT" --lan-ip 192.168.77.1
  assert_equal "$(cat "$OUT/seed.img")" "earlier seed"
  [ -z "$(calls_to mcopy)" ]
}

@test "a seed that cannot be written to the image leaves no configuration behind" {
  stub mcopy <<'BODY'
exit 1
BODY
  run -1 "$SCRIPT" "$OUT" --lan-ip 192.168.77.1
  source_path=$(calls_to mcopy | awk '{print $4}')
  [ -n "$source_path" ]
  [ ! -e "$source_path" ]
}
