#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
}

teardown() {
  harness_teardown
}

# A test file as a script's author would write it, run by a second Bats so the
# outcome under test is the verdict a real test file would get.
verdict_of() {
  local file="$BATS_TEST_TMPDIR/nested.bats"
  {
    printf '%s\n' '#!/usr/bin/env bats'
    printf 'setup() { load "%s"; harness_setup; }\n' "$REPO_ROOT/tools/tests/shell/test_helper/harness"
    printf 'teardown() { harness_teardown; }\n'
    cat
  } > "$file"
  run "$BATS_ROOT/bin/bats" "$file"
}

@test "a script that calls a tool the test did not stub exits non-zero" {
  printf '#!/bin/sh\ndocker ps\n' > "$TEST_ROOT/script.sh"
  run -127 sh "$TEST_ROOT/script.sh"
  # The call was the point of the test, so the teardown must not count it.
  : > "$UNSTUBBED"
  assert_output --partial "docker: not stubbed by this test (called with: ps)"
}

@test "a test whose script swallows that failure still fails" {
  verdict_of <<'NESTED'
@test "swallowed" {
  run sh -c 'docker ps || true'
  assert_success
}
NESTED
  assert_failure
  assert_output --partial "external tools called without a stub: docker"
}

@test "a test that stubs the tool passes" {
  verdict_of <<'NESTED'
@test "stubbed" {
  stub docker <<'BODY'
exit 0
BODY
  run sh -c 'docker ps'
  assert_success
}
NESTED
  assert_success
}

@test "every tool a script under test calls resolves to a stub first" {
  local tool
  for tool in "${HARNESS_EXTERNAL_TOOLS[@]}"; do
    assert_equal "$(command -v "$tool")" "$STUB_BIN/$tool"
  done
}

@test "a stub records its argv on one line even when an argument spans lines" {
  stub docker <<'BODY'
exit 0
BODY
  docker compose run -c $'one\ntwo'
  assert_equal "$(calls_to docker)" "docker compose run -c \$'one\\ntwo'"
}

@test "temporary files and the home directory are the test's own" {
  assert_equal "$(mktemp -d | xargs dirname)" "$BATS_TEST_TMPDIR/tmp"
  assert_equal "$HOME" "$BATS_TEST_TMPDIR/home"
}

@test "a CI job summary is not written to" {
  GITHUB_STEP_SUMMARY=/not/for/tests GITHUB_OUTPUT=/not/for/tests verdict_of <<'NESTED'
@test "unset" {
  assert_equal "${GITHUB_STEP_SUMMARY:-unset}${GITHUB_OUTPUT:-unset}" unsetunset
}
NESTED
  assert_success
}

@test "an installed script sits at its own relative path in the test's tree" {
  script=$(install_script docker/minecraft/scripts/run_restore.sh)
  assert_equal "$script" "$TEST_ROOT/docker/minecraft/scripts/run_restore.sh"
  run diff "$REPO_ROOT/docker/minecraft/scripts/run_restore.sh" "$script"
  assert_success
}

@test "a template renders with the variables the test gives it" {
  printf 'host={{ name }}\n{%% if on %%}yes\n{%% endif %%}' > "$TEST_ROOT/t.j2"
  render_template "$TEST_ROOT/t.j2" '{"name":"h","on":true}' > "$TEST_ROOT/out"
  assert_equal "$(cat "$TEST_ROOT/out")" $'host=h\nyes'
}

@test "a variable the test did not give fails the render" {
  printf '{{ missing }}\n' > "$TEST_ROOT/t.j2"
  run -1 render_template "$TEST_ROOT/t.j2" '{}'
  assert_output --partial "'missing' is undefined"
}
