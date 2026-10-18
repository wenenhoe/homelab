#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script docker/minecraft/scripts/run_restore.sh)
  PHASES="$BATS_TEST_TMPDIR/phases"
  : > "$PHASES"
  export PHASES
  # Each docker call is told apart by what it runs; FAIL_PHASE names the one that fails.
  stub docker <<'BODY'
case "$*" in
  *"tar tf"*)                   phase=preflight ;;
  *"rm -rf"*)                   phase=wipe ;;
  *"ls -A /data"*)              phase=verify ;;
  *"run --rm restore-backup"*)  phase=restore ;;
  *" stop"*)                    phase=stop ;;
  *"up -d"*)                    phase=up ;;
  *) echo "unexpected docker call: $*" >&2; exit 64 ;;
esac
echo "$phase" >> "$PHASES"
[ "${FAIL_PHASE:-}" != "$phase" ]
BODY
}

teardown() {
  harness_teardown
}

phases() {
  tr '\n' ' ' < "$PHASES" | sed 's/ $//'
}

@test "-y runs every phase in order and brings the stack back up" {
  run bash "$SCRIPT" -y
  assert_success
  assert_equal "$(phases)" "preflight stop wipe restore verify up"
}

@test "--yes is -y" {
  run bash "$SCRIPT" --yes
  assert_success
  assert_equal "$(phases)" "preflight stop wipe restore verify up"
}

@test "the stack is brought up with the live compose file" {
  run bash "$SCRIPT" -y
  assert_success
  assert_equal "$(calls_to docker | tail -1)" "docker compose -f compose.yaml up -d"
}

@test "both prompts answered restore the world" {
  run bash "$SCRIPT" <<< $'yes\ndelete'
  assert_success
  assert_equal "$(phases)" "preflight stop wipe restore verify up"
}

@test "anything but yes at the first prompt does nothing" {
  run -1 bash "$SCRIPT" <<< "y"
  assert_output --partial "Restore aborted — confirmation not given."
  assert_equal "$(phases)" ""
}

@test "declining the second prompt stops after the read-only check of the backup" {
  run -1 bash "$SCRIPT" <<< $'yes\nno'
  assert_output --partial "nothing was stopped or deleted"
  assert_equal "$(phases)" "preflight"
}

@test "the second prompt wants delete, not yes" {
  run -1 bash "$SCRIPT" <<< $'yes\nyes'
  assert_output --partial "nothing was stopped or deleted"
  assert_equal "$(phases)" "preflight"
}

@test "a backup that cannot be read stops everything before the stack is touched" {
  FAIL_PHASE=preflight run bash "$SCRIPT" -y
  assert_failure
  assert_equal "$(phases)" "preflight"
}

@test "a failed stop starts the stack again, since nothing was deleted" {
  FAIL_PHASE=stop run bash "$SCRIPT" -y
  assert_failure
  assert_equal "$(phases)" "preflight stop up"
}

@test "a failed wipe leaves the stack stopped" {
  FAIL_PHASE=wipe run bash "$SCRIPT" -y
  assert_failure
  assert_output --partial "so the stack is NOT being started"
  assert_equal "$(phases)" "preflight stop wipe"
}

@test "a failed restore after the wipe leaves the stack stopped" {
  FAIL_PHASE=restore run bash "$SCRIPT" -y
  assert_failure
  assert_output --partial "so the stack is NOT being started"
  assert_equal "$(phases)" "preflight stop wipe restore"
}

@test "a restore that extracted nothing leaves the stack stopped" {
  FAIL_PHASE=verify run bash "$SCRIPT" -y
  assert_failure
  assert_output --partial "so the stack is NOT being started"
  assert_equal "$(phases)" "preflight stop wipe restore verify"
}
