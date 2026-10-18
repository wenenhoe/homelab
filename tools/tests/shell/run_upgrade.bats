#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script docker/minecraft/scripts/run_upgrade.sh)
  # The compose run is what the script decides on: it records the VERSION it
  # was given and where it ran, and exits with $DOCKER_STATUS.
  stub docker <<'BODY'
echo "VERSION=$VERSION cwd=$PWD" >> "$CALLS"
exit "${DOCKER_STATUS:-0}"
BODY
}

teardown() {
  harness_teardown
}

@test "the version argument reaches the compose run" {
  run bash "$SCRIPT" 1.21.11
  assert_success
  assert_output --partial "Starting test-upgrade with VERSION=1.21.11..."
  assert_equal "$(grep '^VERSION=' "$CALLS")" "VERSION=1.21.11 cwd=$TEST_ROOT/docker/minecraft"
}

@test "without an argument the default version is used" {
  run bash "$SCRIPT"
  assert_success
  assert_equal "$(grep '^VERSION=' "$CALLS")" "VERSION=26.1.2 cwd=$TEST_ROOT/docker/minecraft"
}

@test "the compose run is the upgrade service, removed afterwards" {
  run bash "$SCRIPT" 1.21.11
  assert_equal "$(calls_to docker)" "docker --log-level ERROR compose -f compose.upgrade.yaml run --rm test-upgrade"
}

@test "success is reported as such" {
  run bash "$SCRIPT" 1.21.11
  assert_success
  assert_output --partial "Upgrade is successful."
  refute_output --partial "failed"
}

@test "the compose exit status is reported and is the script's own" {
  DOCKER_STATUS=3 run -3 bash "$SCRIPT" 1.21.11
  assert_output --partial "Upgrade failed with exit code: 3"
  refute_output --partial "Upgrade is successful."
}
