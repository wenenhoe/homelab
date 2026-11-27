#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script ansible/scripts/molecule-test-all.sh)
  ROLES="$TEST_ROOT/ansible/roles"
  scenarios foo a b c
  scenarios bar only
  mkdir -p "$ROLES/baz/tasks" "$TEST_ROOT/ansible/molecule-coverage"
  stub git <<'BODY'
echo /fake/toplevel
BODY
  # FAIL_ON names the one scenario that fails, as role:scenario.
  stub molecule <<'BODY'
[ "$(basename "$PWD"):${*: -1}" != "${FAIL_ON:-}" ]
BODY
  stub python3 <<'BODY'
exit 0
BODY
  unset GITHUB_ACTIONS
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

@test "MOLECULE_TIMINGS_FILE gets a tab-separated row for each scenario that ran" {
  MOLECULE_TIMINGS_FILE="$BATS_TEST_TMPDIR/timings.tsv" run bash "$SCRIPT" foo bar
  assert_success
  assert_equal "$(cut -f1,2,4 "$BATS_TEST_TMPDIR/timings.tsv")" "$(printf 'foo\ta\tpassed\nfoo\tb\tpassed\nfoo\tc\tpassed\nbar\tonly\tpassed')"
  assert_regex "$(cut -f3 "$BATS_TEST_TMPDIR/timings.tsv" | tr '\n' ' ')" '^[0-9]+ [0-9]+ [0-9]+ [0-9]+ $'
}

@test "MOLECULE_TIMINGS_FILE records a failed scenario as FAILED and none after it, and the run still fails" {
  MOLECULE_TIMINGS_FILE="$BATS_TEST_TMPDIR/timings.tsv" FAIL_ON=foo:b run -1 bash "$SCRIPT" foo
  assert_equal "$(cut -f1,2,4 "$BATS_TEST_TMPDIR/timings.tsv")" "$(printf 'foo\ta\tpassed\nfoo\tb\tFAILED')"
}

@test "without MOLECULE_TIMINGS_FILE no timings file is written" {
  cd "$BATS_TEST_TMPDIR"
  run bash "$SCRIPT" foo
  assert_success
  assert_equal "$(find "$BATS_TEST_TMPDIR" -name '*.tsv' | wc -l)" "0"
}

# overlap_stub N: a test run ends only once N test runs have started, so a run
# that takes scenarios one at a time fails. FAIL_ON lists the scenarios that fail.
overlap_stub() {
  export BARRIER="$BATS_TEST_TMPDIR/barrier" WANT=$1
  mkdir -p "$BARRIER"
  stub molecule <<'BODY'
[ "${@: -3:1}" = test ] || exit 0
id="$(basename "$PWD"):${*: -1}"
: > "$BARRIER/$id"
for _ in $(seq 100); do
  [ "$(find "$BARRIER" -type f | wc -l)" -ge "$WANT" ] && break
  sleep 0.05
done
echo "output of $id"
[ "$(find "$BARRIER" -type f | wc -l)" -ge "$WANT" ] && [[ " ${FAIL_ON:-} " != *" $id "* ]]
BODY
}

@test "-j needs a positive number" {
  run -2 bash "$SCRIPT" -j 0 foo
  assert_output --partial "Usage:"
  run -2 bash "$SCRIPT" foo -j
  assert_output --partial "Usage:"
  assert_equal "$(calls_to molecule)" ""
}

@test "-j runs that many scenarios at once, across roles" {
  overlap_stub 4
  run bash "$SCRIPT" -j 4 foo bar
  assert_success
  assert_line "All roles passed: foo bar"
}

@test "-j installs every scenario's dependencies, one at a time, before any test starts" {
  run bash "$SCRIPT" -j 2 foo bar
  assert_success
  assert_equal "$(calls_to molecule | awk '{print $(NF-2), $NF}' | head -4 | tr '\n' ' ')" "dependency a dependency b dependency c dependency only "
  assert_equal "$(calls_to molecule | grep -c ' test -s ')" 4
}

@test "-j prints each scenario's output under its own heading and keeps the table in scenario order" {
  overlap_stub 2
  run bash "$SCRIPT" -j 2 foo -s a -s b
  assert_success
  assert_output --partial "--- foo: a (passed) ---
output of foo:a"
  assert_output --partial "--- foo: b (passed) ---
output of foo:b"
  assert_equal "$(grep -E '^\| foo' <<< "$output" | cut -d'|' -f3 | tr -d ' ' | tr '\n' ' ')" "a b "
}

@test "-j starts no further scenario of a failed role, runs the others and fails the run" {
  overlap_stub 2
  # Both running scenarios fail: a passing one that ended first would free a slot for c before the failure was known.
  FAIL_ON="foo:a foo:b" run -1 bash "$SCRIPT" -j 2 foo bar
  assert_line "FAILED: foo"
  assert_line --regexp '^\| foo \| a \| [0-9]+ \| FAILED \|$'
  assert_line --regexp '^\| bar \| only \| [0-9]+ \| passed \|$'
  run ! grep -c ' test -s c$' "$CALLS"
}

@test "-j with MOLECULE_TIMINGS_FILE is refused and runs nothing" {
  MOLECULE_TIMINGS_FILE="$BATS_TEST_TMPDIR/timings.tsv" run -2 bash "$SCRIPT" -j 2 foo
  assert_output --partial "cannot be used with MOLECULE_TIMINGS_FILE"
  assert_equal "$(calls_to molecule)" ""
}

# coverage_checks: the role of each coverage report, in call order.
coverage_checks() {
  calls_to python3 | grep ' report ' | sed -E 's/^.*--role ([^ ]+).*$/\1/' | tr '\n' ' ' | sed 's/ $//'
}

@test "a full run of a role ends by holding it to its coverage floor" {
  run bash "$SCRIPT" foo bar
  assert_success
  assert_equal "$(coverage_checks)" "foo bar"
  assert_equal "$(calls_to python3 | head -2)" "python3 -m molecule_cov.cli inventory ../roles/foo --coverage-dir .data
python3 -m molecule_cov.cli report --coverage-dir .data --role foo --thresholds-file thresholds.yaml"
}

@test "a role under its coverage floor fails the run" {
  stub python3 <<'BODY'
[[ "$* " != *" report "*" --role foo "* ]]
BODY
  run -1 bash "$SCRIPT" foo bar
  assert_line "FAILED: foo (coverage)"
}

@test "a role with a failed scenario is not checked for coverage, the others are" {
  FAIL_ON=foo:b run -1 bash "$SCRIPT" foo bar
  assert_equal "$(coverage_checks)" "bar"
}

@test "a full run starts from no coverage data for its roles and leaves other roles' alone" {
  local data="$TEST_ROOT/ansible/molecule-coverage/.data"
  mkdir -p "$data/foo" "$data/bar"
  : > "$data/foo/removed_scenario.jsonl"
  : > "$data/bar/only.jsonl"
  run bash "$SCRIPT" foo
  assert_success
  assert [ ! -e "$data/foo/removed_scenario.jsonl" ]
  assert [ -e "$data/bar/only.jsonl" ]
}

@test "-s says coverage is not checked and keeps the data" {
  local data="$TEST_ROOT/ansible/molecule-coverage/.data/foo"
  mkdir -p "$data"
  : > "$data/b.jsonl"
  run bash "$SCRIPT" foo -s a
  assert_success
  assert_line "Coverage not checked: -s runs only some of a role's scenarios."
  assert_equal "$(calls_to python3)" ""
  assert [ -e "$data/b.jsonl" ]
}

@test "in GitHub Actions the run leaves coverage to its own job" {
  GITHUB_ACTIONS=true run bash "$SCRIPT" foo
  assert_success
  assert_equal "$(calls_to python3)" ""
}
