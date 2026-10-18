#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script ansible/scripts/molecule-test-all.sh)
  ROLES="$TEST_ROOT/ansible/roles"
  scenarios foo a b c
  scenarios bar only
  mkdir -p "$ROLES/baz/tasks"
  stub git <<'BODY'
echo /fake/toplevel
BODY
  # FAIL_ON names the one scenario that fails, as role:scenario.
  stub molecule <<'BODY'
[ "$(basename "$PWD"):${*: -1}" != "${FAIL_ON:-}" ]
BODY
}

teardown() {
  harness_teardown
}

# scenarios ROLE NAME...: a role with a molecule scenario of each name.
scenarios() {
  local role=$1 name
  shift
  for name in "$@"; do
    mkdir -p "$ROLES/$role/molecule/$name"
    : > "$ROLES/$role/molecule/$name/molecule.yml"
  done
}

# molecule_runs: the scenario of each molecule call, in call order.
molecule_runs() {
  calls_to molecule | sed -E 's/^.* test -s //' | tr '\n' ' ' | sed 's/ $//'
}

@test "-s with more than one role is a usage error and runs nothing" {
  run -2 bash "$SCRIPT" foo bar -s a
  assert_output --partial "-s requires exactly one role"
  assert_equal "$(calls_to molecule)" ""
}

@test "-s with no role is a usage error and runs nothing" {
  run -2 bash "$SCRIPT" -s a
  assert_output --partial "-s requires exactly one role"
  assert_equal "$(calls_to molecule)" ""
}

@test "-s without a scenario name is a usage error" {
  run -2 bash "$SCRIPT" foo -s
  assert_output --partial "Usage:"
}

@test "-s with one role runs only the named scenarios, in the order given" {
  run bash "$SCRIPT" foo -s c -s a
  assert_success
  assert_equal "$(molecule_runs)" "c a"
}

@test "without -s a role's scenarios run one at a time in name order against the base config" {
  run bash "$SCRIPT" foo
  assert_success
  assert_equal "$(calls_to molecule)" "molecule --base-config /fake/toplevel/.config/molecule/config.yml test -s a
molecule --base-config /fake/toplevel/.config/molecule/config.yml test -s b
molecule --base-config /fake/toplevel/.config/molecule/config.yml test -s c"
}

@test "with no role named, every role that has molecule scenarios runs and no other" {
  run bash "$SCRIPT"
  assert_success
  assert_output --partial "All roles passed: bar foo"
  assert_equal "$(molecule_runs)" "only a b c"
}

@test "a failing scenario stops its own role at that scenario" {
  FAIL_ON=foo:b run -1 bash "$SCRIPT" foo
  assert_equal "$(molecule_runs)" "a b"
}

@test "a failing scenario does not stop the other roles" {
  FAIL_ON=foo:b run -1 bash "$SCRIPT" foo bar
  assert_line "FAILED: foo"
  assert_equal "$(molecule_runs)" "a b only"
}

@test "all passing ends in success" {
  run bash "$SCRIPT" foo bar
  assert_success
  assert_line "All roles passed: foo bar"
}

@test "the timings table has a row for every scenario that ran and its result" {
  FAIL_ON=foo:b run -1 bash "$SCRIPT" foo bar
  assert_line "| Role | Scenario | Seconds | Result |"
  assert_line --regexp '^\| foo \| a \| [0-9]+ \| passed \|$'
  assert_line --regexp '^\| foo \| b \| [0-9]+ \| FAILED \|$'
  assert_line --regexp '^\| bar \| only \| [0-9]+ \| passed \|$'
  run ! grep -c '| foo | c |' <<< "$output"
}

@test "the table is appended to the job summary when there is one" {
  GITHUB_STEP_SUMMARY="$BATS_TEST_TMPDIR/summary.md" run bash "$SCRIPT" bar
  assert_success
  run cat "$BATS_TEST_TMPDIR/summary.md"
  assert_line "### Molecule scenario timings"
  assert_line --regexp '^\| bar \| only \| [0-9]+ \| passed \|$'
}

@test "no summary file is written when there is no job summary" {
  run bash "$SCRIPT" bar
  assert_success
  assert_equal "$(find "$BATS_TEST_TMPDIR" -name '*.md' | wc -l | tr -d ' ')" 0
}
