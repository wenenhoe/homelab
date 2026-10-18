#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tools/openbao_utils/scripts/snapshot-push.sh)
  SECRETS="$BATS_TEST_TMPDIR/secrets"
  EVENTS="$BATS_TEST_TMPDIR/events"
  SECRET_SEEN="$BATS_TEST_TMPDIR/secret-seen"
  CONFS="$BATS_TEST_TMPDIR/confs"
  mkdir -p "$SECRETS" "$CONFS"
  : > "$EVENTS"
  export EVENTS SECRET_SEEN CONFS

  stub python3 <<BODY
printf '%s\n' deploy 10.0.0.9 /keys/id example.test "$SECRETS"
BODY
  stub stty <<'BODY'
exit 0
BODY
  # FAIL_STEP lists the steps of the run that fail, comma separated: ssh, login,
  # snapshot, gpg, kv, push-r2, push-b2. Only the pushes are ever listed together.
  stub ssh <<'BODY'
[ "${FAIL_STEP:-}" != ssh ] || exit 255
echo "FAKE ROOT CA"
BODY
  stub gpg <<'BODY'
[ "${FAIL_STEP:-}" != gpg ] || exit 2
while [ "$#" -gt 0 ]; do
  [ "$1" = --output ] && echo encrypted > "$2"
  shift
done
BODY
  stub bao <<'BODY'
case "$1 $2" in
  "write -field=token")
    [ "${FAIL_STEP:-}" != login ] || exit 2
    secret_file=${5#secret_id=@}
    cat "$secret_file" > "$SECRET_SEEN"
    echo tok123 ;;
  "kv get")
    [ "${FAIL_STEP:-}" != kv ] || exit 2
    echo "value-of:${*: -1}" ;;
  "operator raft")
    [ "${FAIL_STEP:-}" != snapshot ] || exit 2
    echo snapshot > "${*: -1}" ;;
  "token revoke") echo "revoke $BAO_TOKEN" >> "$EVENTS" ;;
  *) echo "unexpected bao call: $*" >&2; exit 64 ;;
esac
BODY
  stub docker <<'BODY'
for arg in "$@"; do
  case "$arg" in
    *:openbao-snapshots/) remote=${arg%%:*} ;;
    *rclone.conf:*) conf=${arg%%:*} ;;
  esac
done
echo "push $remote" >> "$EVENTS"
stat -c %a "$conf" > "$CONFS/$remote.mode"
cp "$conf" "$CONFS/$remote.conf"
case ",${FAIL_STEP:-}," in *",push-$remote,"*) exit 1 ;; esac
BODY
  printf 'S3CR3T\n' > "$SECRETS/openbao-controller-secret-id"
}

teardown() {
  harness_teardown
}

events() {
  tr '\n' '|' < "$EVENTS" | sed 's/|$//'
}

@test "both pushes succeed, the token is revoked and nothing is left in the scratch directory" {
  run sh "$SCRIPT" role-1
  assert_success
  assert_output --partial "Done: snapshot-"
  assert_equal "$(events)|$(ls -A "$TMPDIR")" "push r2|push b2|revoke tok123|"
}

@test "the role_id is passed to the login" {
  run sh "$SCRIPT" role-1
  assert_success
  assert_equal "$(calls_to bao | sed -n 1p | cut -d@ -f1)" "bao write -field=token auth/approle/login role_id=role-1 secret_id="
}

@test "a missing role_id is a usage error and touches nothing" {
  run -2 sh "$SCRIPT"
  assert_output --partial "usage: snapshot-push.sh <role_id>"
  assert_equal "$(cat "$CALLS")|$(ls -A "$TMPDIR")" "|"
}

@test "the cached secret_id reaches the login as a file, without its newline, and never as an argument" {
  run sh "$SCRIPT" role-1
  assert_success
  run ! grep -F S3CR3T "$CALLS"
  assert_equal "$(wc -c < "$SECRET_SEEN" | tr -d ' ')|$(cat "$SECRET_SEEN")" "6|S3CR3T"
}

@test "a prompted secret_id reaches the login the same way" {
  rm "$SECRETS/openbao-controller-secret-id"
  run sh "$SCRIPT" role-1 <<< "PROMPTED"
  assert_success
  run ! grep -F PROMPTED "$CALLS"
  assert_equal "$(wc -c < "$SECRET_SEEN" | tr -d ' ')|$(cat "$SECRET_SEEN")" "8|PROMPTED"
}

@test "an empty cached secret_id is not used" {
  : > "$SECRETS/openbao-controller-secret-id"
  run sh "$SCRIPT" role-1 <<< "PROMPTED"
  assert_success
  assert_equal "$(cat "$SECRET_SEEN")" "PROMPTED"
}

@test "rclone.conf is mode 0600 for both pushes" {
  run sh "$SCRIPT" role-1
  assert_success
  assert_equal "$(cat "$CONFS/r2.mode" "$CONFS/b2.mode" | tr '\n' ' ')" "600 600 "
}

@test "each remote's section carries that provider's own credentials" {
  run sh "$SCRIPT" role-1
  assert_success
  run awk '/^\[/ { section = $0 } /^(access_key_id|secret_access_key) / { print section, $0 }' "$CONFS/r2.conf"
  assert_output "[r2] access_key_id = value-of:cloud_credentials/leaf/cloudflare-r2-openbao-snapshot-write-access-key
[r2] secret_access_key = value-of:cloud_credentials/leaf/cloudflare-r2-openbao-snapshot-write-secret-key
[b2] access_key_id = value-of:cloud_credentials/leaf/backblaze-b2-openbao-snapshot-write-access-key
[b2] secret_access_key = value-of:cloud_credentials/leaf/backblaze-b2-openbao-snapshot-write-secret-key"
}

@test "a failed R2 push still attempts B2, then fails naming r2" {
  FAIL_STEP=push-r2 run -1 sh "$SCRIPT" role-1
  assert_output --partial "Push to r2 FAILED"
  assert_output --partial "One or more pushes failed: r2"
  assert_equal "$(events)" "push r2|push b2|revoke tok123"
}

@test "a failed B2 push after R2 fails naming b2" {
  FAIL_STEP=push-b2 run -1 sh "$SCRIPT" role-1
  assert_output --partial "One or more pushes failed: b2"
  assert_equal "$(events)" "push r2|push b2|revoke tok123"
}

@test "both pushes failing names both" {
  FAIL_STEP=push-r2,push-b2 run -1 sh "$SCRIPT" role-1
  assert_output --partial "One or more pushes failed: r2 b2"
}

@test "a failed snapshot save revokes the token and removes the scratch directory" {
  FAIL_STEP=snapshot run -2 sh "$SCRIPT" role-1
  assert_equal "$(events)|$(ls -A "$TMPDIR")" "revoke tok123|"
}

@test "a failed encryption revokes the token and removes the scratch directory" {
  FAIL_STEP=gpg run -2 sh "$SCRIPT" role-1
  assert_equal "$(events)|$(ls -A "$TMPDIR")" "revoke tok123|"
}

@test "a failed credential read revokes the token and removes the scratch directory" {
  FAIL_STEP=kv run -2 sh "$SCRIPT" role-1
  assert_equal "$(events)|$(ls -A "$TMPDIR")" "revoke tok123|"
}

@test "a failed login has no token to revoke and still removes the scratch directory" {
  FAIL_STEP=login run -2 sh "$SCRIPT" role-1
  assert_equal "$(events)|$(ls -A "$TMPDIR")" "|"
}

@test "a failed root cert fetch calls nothing of OpenBao and removes the scratch directory" {
  FAIL_STEP=ssh run -255 sh "$SCRIPT" role-1
  assert_equal "$(calls_to bao)|$(ls -A "$TMPDIR")" "|"
}
