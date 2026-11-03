#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tools/rebuild_check/scripts/retire_vm.sh)
  export DUMP_DIR="$BATS_TEST_TMPDIR/dumps"
  mkdir -p "$DUMP_DIR"
  DUMP="$DUMP_DIR/vzdump-qemu-204-2026_11_03-10_00_00.vma.zst"
  export QM_NAME=play QM_STATUS=stopped
  stub mountpoint <<'BODY'
[ "${DUMP_UNMOUNTED-}" != 1 ]
BODY
  stub pvesm <<'BODY'
true
BODY
  # `qm config` of a VMID with no VM fails; `qm status` prints one line.
  stub qm <<'BODY'
case "$1" in
  config) printf 'cores: 4\nname: %s\nmemory: 4096\n' "$QM_NAME" ;;
  status) printf 'status: %s\n' "$QM_STATUS" ;;
esac
BODY
  # vzdump writes the archive and its log under the storage's directory.
  stub vzdump <<'BODY'
case "${VZDUMP_WRITES:-archive}" in
  archive) printf 'ZSTDATA\n' > "$DUMP_DIR/vzdump-qemu-$1-2026_11_03-10_00_00.vma.zst" ;;
  empty) : > "$DUMP_DIR/vzdump-qemu-$1-2026_11_03-10_00_00.vma.zst" ;;
esac
BODY
  stub fstrim <<'BODY'
true
BODY
}

teardown() {
  harness_teardown
}

@test "dump writes the archive with zstd to the dump storage and says where" {
  run -0 "$SCRIPT" dump 204 play

  assert_output --partial "dumped VM 204 to $DUMP "
  [ -s "$DUMP" ]
  run calls_to vzdump
  assert_output "vzdump 204 --storage vzdump --compress zstd --mode stop"
}

@test "dump refuses a VM whose name differs and runs no vzdump" {
  QM_NAME=security run -1 "$SCRIPT" dump 204 play

  assert_output "VM 204 is named 'security', not 'play'"
  run calls_to vzdump
  assert_output ""
}

@test "dump refuses a running VM" {
  QM_STATUS=running run -1 "$SCRIPT" dump 204 play

  assert_output "VM 204 is not stopped"
  run calls_to vzdump
  assert_output ""
}

@test "dump refuses when the dump storage is not mounted" {
  DUMP_UNMOUNTED=1 run -1 "$SCRIPT" dump 204 play

  assert_output "$DUMP_DIR is not a mount point: the dump storage is not mounted"
  run calls_to vzdump
  assert_output ""
}

@test "dump keeps a dump that exists and does not make a second" {
  printf 'OLD\n' > "$DUMP"

  run -1 "$SCRIPT" dump 204 play

  assert_output --partial "VM 204 already has a dump"
  [ "$(cat "$DUMP")" = OLD ]
  run calls_to vzdump
  assert_output ""
}

@test "dump fails when vzdump leaves nothing or an empty archive" {
  VZDUMP_WRITES=none run -1 "$SCRIPT" dump 204 play
  assert_output "expected one dump of VM 204 in $DUMP_DIR, found 0"

  VZDUMP_WRITES=empty run -1 "$SCRIPT" dump 204 play
  assert_output "the dump $DUMP is empty"
}

@test "a dump of another VM whose id starts the same does not count as this VM's" {
  printf 'OTHER\n' > "$DUMP_DIR/vzdump-qemu-2041-2026_11_03-10_00_00.vma.zst"

  run -0 "$SCRIPT" dump 204 play

  [ "$(cat "$DUMP")" = "ZSTDATA" ]
}

@test "destroy removes the stopped VM and its unreferenced disks once its dump is there" {
  printf 'ZSTDATA\n' > "$DUMP"

  run -0 "$SCRIPT" destroy 204 play

  assert_output "destroyed VM 204; its dump is $DUMP"
  run calls_to qm
  assert_output --partial "qm destroy 204 --purge 1 --destroy-unreferenced-disks 1"
}

@test "destroy without a dump, with an empty one or with a running VM destroys nothing" {
  run -1 "$SCRIPT" destroy 204 play
  assert_output "expected one dump of VM 204 in $DUMP_DIR, found 0"

  : > "$DUMP"
  run -1 "$SCRIPT" destroy 204 play
  assert_output "the dump $DUMP is empty"

  printf 'ZSTDATA\n' > "$DUMP"
  QM_STATUS=running run -1 "$SCRIPT" destroy 204 play
  assert_output "VM 204 is not stopped"

  QM_NAME=security run -1 "$SCRIPT" destroy 204 play
  assert_output "VM 204 is named 'security', not 'play'"

  run calls_to qm
  refute_output --partial "qm destroy"
}

@test "drop-dump deletes that VM's archive and log and trims the volume, leaving other dumps" {
  printf 'ZSTDATA\n' > "$DUMP"
  printf 'log\n' > "$DUMP.log"
  printf 'OTHER\n' > "$DUMP_DIR/vzdump-qemu-2041-2026_11_03-10_00_00.vma.zst"

  run -0 "$SCRIPT" drop-dump 204

  [ ! -e "$DUMP" ]
  [ ! -e "$DUMP.log" ]
  [ -e "$DUMP_DIR/vzdump-qemu-2041-2026_11_03-10_00_00.vma.zst" ]
  run calls_to fstrim
  assert_output "fstrim -v $DUMP_DIR"
}

@test "drop-dump with no dump fails and trims nothing" {
  run -1 "$SCRIPT" drop-dump 204

  assert_output "no dump of VM 204 in $DUMP_DIR"
  run calls_to fstrim
  assert_output ""
}

@test "a wrong action, a missing argument or a VMID that is not a number prints the usage" {
  run -2 "$SCRIPT" wipe 204 play
  assert_output --partial "usage:"
  run -2 "$SCRIPT" dump 204
  assert_output --partial "usage:"
  run -2 "$SCRIPT" dump '204;x' play
  assert_output --partial "usage:"
}
