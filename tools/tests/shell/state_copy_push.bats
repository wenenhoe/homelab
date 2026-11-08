#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tools/tofu_state/state-copy-push.sh)
  CONFIG="$BATS_TEST_TMPDIR/config"
  EVENTS="$BATS_TEST_TMPDIR/events"
  OUT="$BATS_TEST_TMPDIR/out"
  mkdir -p "$CONFIG" "$OUT"
  : > "$EVENTS"
  export TOFU_CONFIG_DIR="$CONFIG" EVENTS OUT
  # A runner or shell may already export these; the test starts without them.
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_ENDPOINT_URL_S3 TF_ENCRYPTION STATE_COPY_ACCESS_KEY_ID

  # `export KEY=value` lines, as write_env_file writes them.
  printf '%s\n' \
    "export AWS_ACCESS_KEY_ID=r2-key" \
    "export AWS_SECRET_ACCESS_KEY=r2-secret" \
    "export TF_ENCRYPTION='key_provider \"pbkdf2\" \"main\" {}'" > "$CONFIG/state-backend.env"
  printf '%s\n' \
    "export STATE_COPY_ACCESS_KEY_ID=b2-key" \
    "export STATE_COPY_SECRET_ACCESS_KEY=b2-secret" \
    "export STATE_COPY_ENDPOINT=https://s3.eu-central-003.backblazeb2.com" \
    "export STATE_COPY_REGION=eu-central-003" \
    "export STATE_COPY_BUCKET=opentofu-state-b2" > "$CONFIG/state-copy.env"

  # FAIL_STEP is one of: pull, empty, gpg, push.
  stub tofu <<'BODY'
echo pull >> "$EVENTS"
echo "${AWS_ACCESS_KEY_ID:-}|${STATE_COPY_ACCESS_KEY_ID:-}" > "$OUT/tofu-env"
[ "${FAIL_STEP:-}" != pull ] || exit 3
[ "${FAIL_STEP:-}" != empty ] || exit 0
echo '{"version":4,"serial":7}'
BODY
  stub gpg <<'BODY'
echo gpg >> "$EVENTS"
[ "${FAIL_STEP:-}" != gpg ] || exit 2
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output) enc=$2 ;;
    --recipient-file) echo "$2" > "$OUT/recipient" ;;
  esac
  last=$1
  shift
done
cp "$last" "$OUT/gpg-input"
echo encrypted > "$enc"
BODY
  stub docker <<'BODY'
echo push >> "$EVENTS"
for arg in "$@"; do
  case "$arg" in
    *rclone.conf:*) conf=${arg%%:*} ;;
    *:/data:ro) staging=${arg%%:*} ;;
    b2:*) dest=$arg ;;
    /data/*) object=$arg ;;
  esac
done
stat -c %a "$conf" > "$OUT/conf-mode"
cp "$conf" "$OUT/rclone.conf"
ls -A "$staging" > "$OUT/staged"
echo "$dest" > "$OUT/dest"
echo "$object" > "$OUT/object"
echo "${AWS_ACCESS_KEY_ID:-}|${STATE_COPY_ACCESS_KEY_ID:-}" > "$OUT/docker-env"
[ "${FAIL_STEP:-}" != push ] || exit 1
BODY
}

teardown() {
  harness_teardown
}

events() {
  tr '\n' '|' < "$EVENTS" | sed 's/|$//'
}

@test "a run pulls, encrypts and pushes, and leaves nothing in the scratch directory" {
  run sh "$SCRIPT"
  assert_success
  assert_output --partial "Done: state-"
  assert_equal "$(events)|$(ls -A "$TMPDIR")" "pull|gpg|push|"
}

@test "the object is a new timestamped name under state/ in the copy bucket" {
  run sh "$SCRIPT"
  assert_success
  run grep -E '^/data/state-[0-9]{8}T[0-9]{6}Z\.json\.gpg$' "$OUT/object"
  assert_success
  assert_equal "$(cat "$OUT/dest")" "b2:opentofu-state-b2/state/"
}

@test "only copy is used, so the push cannot overwrite or delete" {
  run sh "$SCRIPT"
  assert_success
  assert_equal "$(calls_to docker | grep -c ' copy ')|$(calls_to docker | grep -cE ' (sync|move|delete|purge)')" "1|0"
}

@test "the plaintext pull is what gets encrypted, to the backup key" {
  run sh "$SCRIPT"
  assert_success
  assert_equal "$(cat "$OUT/gpg-input")" '{"version":4,"serial":7}'
  assert_equal "$(basename "$(cat "$OUT/recipient")")" "backup-gpg-public-key.asc"
}

@test "only the ciphertext reaches the container" {
  run sh "$SCRIPT"
  assert_success
  assert_equal "$(cat "$OUT/staged")" "$(basename "$(cat "$OUT/object")")"
}

@test "Tofu sees the R2 environment only and rclone sees the B2 environment only" {
  run sh "$SCRIPT"
  assert_success
  assert_equal "$(cat "$OUT/tofu-env")" "r2-key|"
  assert_equal "$(cat "$OUT/docker-env")" "|"
}

@test "rclone.conf is mode 0600 and carries the copy key and endpoint" {
  run sh "$SCRIPT"
  assert_success
  assert_equal "$(cat "$OUT/conf-mode")" "600"
  run awk '/^(access_key_id|secret_access_key|endpoint|region) / { print }' "$OUT/rclone.conf"
  assert_output "access_key_id = b2-key
secret_access_key = b2-secret
endpoint = https://s3.eu-central-003.backblazeb2.com
region = eu-central-003"
}

@test "a missing env file stops before anything runs" {
  rm "$CONFIG/state-copy.env"
  run -1 sh "$SCRIPT"
  assert_output --partial "state-copy.env; run tools/cloud_credentials/create_state_keys.py"
  assert_equal "$(events)|$(ls -A "$TMPDIR")" "|"
}

@test "a failed pull makes no copy and removes the scratch directory" {
  FAIL_STEP=pull run -3 sh "$SCRIPT"
  assert_equal "$(events)|$(ls -A "$TMPDIR")" "pull|"
}

@test "an empty pull makes no copy and removes the scratch directory" {
  FAIL_STEP=empty run -1 sh "$SCRIPT"
  assert_output --partial "printed nothing"
  assert_equal "$(events)|$(ls -A "$TMPDIR")" "pull|"
}

@test "a failed encryption pushes nothing and removes the scratch directory" {
  FAIL_STEP=gpg run -2 sh "$SCRIPT"
  assert_equal "$(events)|$(ls -A "$TMPDIR")" "pull|gpg|"
}

@test "a failed push fails the run and removes the scratch directory" {
  FAIL_STEP=push run -1 sh "$SCRIPT"
  assert_output --partial "Push to b2 FAILED"
  assert_equal "$(events)|$(ls -A "$TMPDIR")" "pull|gpg|push|"
}
