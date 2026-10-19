# Shared by every shell test file: `load test_helper/harness`, call
# harness_setup from setup() and harness_teardown from teardown().
#
# Every external tool a script under test calls has a stub in a directory that
# comes first on PATH. Until a test replaces it with `stub`, it fails and
# records the call, so a test that forgets one fails instead of running the
# real tool. Add a tool to HARNESS_EXTERNAL_TOOLS when a script under test
# starts to call it; the tools a script runs on the runner's own userland
# (date, stat, tar, ls, find, du) are not listed.
HARNESS_EXTERNAL_TOOLS=(bao curl docker git gpg molecule openssl python3 ssh stty)

harness_setup() {
  # `run` flags and `run !` need 1.5.0.
  bats_require_minimum_version 1.5.0
  bats_load_library bats-support
  bats_load_library bats-assert

  REPO_ROOT=$(cd "$BATS_TEST_DIRNAME/../../.." && pwd)
  # uv keeps its cache and interpreters under $HOME, which is redirected below.
  RENDER_UV_CACHE_DIR=${UV_CACHE_DIR:-$(uv cache dir)}
  RENDER_UV_PYTHON_DIR=${UV_PYTHON_INSTALL_DIR:-$(uv python dir)}
  TEST_ROOT="$BATS_TEST_TMPDIR/tree"
  STUB_BIN="$BATS_TEST_TMPDIR/stubs"
  CALLS="$BATS_TEST_TMPDIR/calls"
  UNSTUBBED="$BATS_TEST_TMPDIR/unstubbed"
  mkdir -p "$TEST_ROOT" "$STUB_BIN" "$BATS_TEST_TMPDIR/tmp" "$BATS_TEST_TMPDIR/home"
  : > "$CALLS"
  : > "$UNSTUBBED"

  # A script's scratch directories and anything it writes under $HOME land in
  # the test's own directory, and a CI run's job summary and outputs are not
  # appended to.
  export CALLS UNSTUBBED TMPDIR="$BATS_TEST_TMPDIR/tmp" HOME="$BATS_TEST_TMPDIR/home"
  unset GITHUB_STEP_SUMMARY GITHUB_OUTPUT

  local tool
  for tool in "${HARNESS_EXTERNAL_TOOLS[@]}"; do
    cat > "$STUB_BIN/$tool" <<'BODY'
#!/usr/bin/env bash
printf '%s\n' "${0##*/}" >> "$UNSTUBBED"
printf '%s: not stubbed by this test (called with: %s)\n' "${0##*/}" "$*" >&2
exit 127
BODY
    chmod +x "$STUB_BIN/$tool"
  done
  PATH="$STUB_BIN:$PATH"
}

# A script that tolerates a failing command (`|| true`, `if ! ...`) would hide a
# forgotten stub from its exit status, so the call record is checked here too.
harness_teardown() {
  if [ -s "$UNSTUBBED" ]; then
    fail "external tools called without a stub: $(sort -u "$UNSTUBBED" | tr '\n' ' ')"
  fi
}

# stub NAME <<'BODY' ... BODY: replaces NAME with an executable that appends
# its argv, one line, to $CALLS and then runs BODY.
stub() {
  {
    cat <<'HEAD'
#!/usr/bin/env bash
# One write per call, so two stubs started together in a pipeline cannot interleave their records.
record=$(printf '%s' "${0##*/}"; printf ' %q' "$@")
printf '%s\n' "$record" >> "$CALLS"
HEAD
    cat
  } > "$STUB_BIN/$1"
  chmod +x "$STUB_BIN/$1"
}

# calls_to NAME: the lines $CALLS holds for NAME, in call order.
calls_to() {
  grep "^$1 " "$CALLS" || true
}

# install_script PATH: copies a script from the repository into the test's own
# tree at the same relative path, so what it finds relative to itself is the
# test's directory, and prints the copy's path.
install_script() {
  mkdir -p "$TEST_ROOT/$(dirname "$1")"
  cp "$REPO_ROOT/$1" "$TEST_ROOT/$1"
  printf '%s\n' "$TEST_ROOT/$1"
}

# render_template TEMPLATE VARIABLES_JSON: renders a Jinja2 template from the
# file with the Jinja2 locked in uv.lock, and prints the result. A variable the
# template uses and the JSON lacks fails the render. To run the result,
# redirect it into a file and make that executable.
render_template() {
  # uv leaves a lock file in TMPDIR; the script under test's scratch directory
  # is checked empty afterwards, so the render gets one of its own.
  mkdir -p "$BATS_TEST_TMPDIR/render-tmp"
  TMPDIR="$BATS_TEST_TMPDIR/render-tmp" UV_CACHE_DIR="$RENDER_UV_CACHE_DIR" UV_PYTHON_INSTALL_DIR="$RENDER_UV_PYTHON_DIR" \
    uv run --frozen --project "$REPO_ROOT" python -I \
    "$REPO_ROOT/tools/tests/shell/test_helper/render_template.py" "$1" "$2"
}
