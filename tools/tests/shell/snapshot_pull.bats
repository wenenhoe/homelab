#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tools/openbao_utils/scripts/snapshot-pull.sh)
  OUT_DIR="$BATS_TEST_TMPDIR/out"
  OUT="$OUT_DIR/restore.snap"
  CONFS="$BATS_TEST_TMPDIR/confs"
  EVENTS="$BATS_TEST_TMPDIR/events"
  mkdir -p "$OUT_DIR" "$CONFS"
  : > "$EVENTS"
  export EVENTS CONFS

  R2_ANSWERS=$'acct1\nR2KEYID\nR2SECRET\n/keys/private.asc'
  B2_ANSWERS=$'eu-central-003\nB2KEYID\nB2SECRET\n/keys/private.asc'
  export LIST_R2=$'snapshot-20260101T000000Z.snap.gpg\nsnapshot-20260301T000000Z.snap.gpg\nsnapshot-20260201T000000Z.snap.gpg\nnotes.txt'
  export LIST_B2=$'snapshot-20260101T000000Z.snap.gpg'

  stub stty <<'BODY'
exit 0
BODY
  stub gpgconf <<'BODY'
echo "agent killed" >> "$EVENTS"
BODY
  # FAIL_STEP lists the steps that fail, comma separated: list-r2, copy-r2,
  # list-b2, copy-b2, import, decrypt.
  stub docker <<'BODY'
fails() { case ",${FAIL_STEP:-}," in *",$1,"*) return 0 ;; esac; return 1; }
for arg in "$@"; do
  case "$arg" in
    *rclone.conf:*) conf=${arg%%:*} ;;
    *:/data) in_dir=${arg%%:*} ;;
    r2:openbao-snapshots/* | b2:openbao-snapshots/*) src=$arg ;;
  esac
done
remote=${src%%:*}
case " $* " in
  *" lsf "*)
    echo "list $remote" >> "$EVENTS"
    stat -c %a "$conf" > "$CONFS/$remote.mode"
    cp "$conf" "$CONFS/$remote.conf"
    fails "list-$remote" && exit 1
    if [ "$remote" = r2 ]; then printf '%s\n' "$LIST_R2"; else printf '%s\n' "$LIST_B2"; fi ;;
  *" copyto "*)
    name=${src#*:openbao-snapshots/}
    echo "copy $remote $name" >> "$EVENTS"
    fails "copy-$remote" && exit 1
    echo encrypted > "$in_dir/$name" ;;
esac
BODY
  stub gpg <<'BODY'
case " $* " in
  *" --import "*)
    case ",${FAIL_STEP:-}," in *",import,"*) exit 2 ;; esac
    echo "import ${*: -1}" >> "$EVENTS" ;;
  *" --decrypt "*)
    case ",${FAIL_STEP:-}," in *",decrypt,"*) exit 2 ;; esac
    out=
    while [ "$#" -gt 0 ]; do
      [ "$1" = --output ] && out=$2
      shift
    done
    printf "${DECRYPTED:-\\037\\213snapshot}" > "$out"
    echo "decrypt" >> "$EVENTS" ;;
esac
BODY
}

teardown() {
  harness_teardown
}

events() {
  tr '\n' '|' < "$EVENTS" | sed 's/|$//'
}

scratch_and_partial() {
  printf '%s|%s' "$(ls -A "$TMPDIR")" "$(find "$OUT_DIR" -name '*.partial')"
}

@test "the newest snapshot by name is fetched, decrypted and left at OUTPUT with nothing else behind" {
  run sh "$SCRIPT" r2 "$OUT" <<< "$R2_ANSWERS"
  assert_success
  assert_equal "$(events)" "list r2|copy r2 snapshot-20260301T000000Z.snap.gpg|import /keys/private.asc|decrypt|agent killed"
  assert_equal "$(stat -c %a "$OUT")|$(scratch_and_partial)" "600||"
  assert_output --partial "Wrote $OUT from snapshot-20260301T000000Z.snap.gpg"
}

@test "with no provider R2 is tried first and B2 is not asked for" {
  run sh "$SCRIPT" "" "$OUT" <<< "$R2_ANSWERS"
  assert_success
  assert_equal "$(events | cut -d'|' -f1-2)" "list r2|copy r2 snapshot-20260301T000000Z.snap.gpg"
  run ! test -e "$CONFS/b2.conf"
}

@test "a failing R2 falls back to B2 and asks for B2's credential" {
  FAIL_STEP=list-r2 run sh "$SCRIPT" "" "$OUT" <<< "$R2_ANSWERS"$'\n'"$B2_ANSWERS"
  assert_success
  assert_equal "$(events | cut -d'|' -f1-3)" "list r2|list b2|copy b2 snapshot-20260101T000000Z.snap.gpg"
  assert_output --partial "Listing r2 FAILED"
}

@test "a failed R2 copy falls back to B2 as well" {
  FAIL_STEP=copy-r2 run sh "$SCRIPT" "" "$OUT" <<< "$R2_ANSWERS"$'\n'"$B2_ANSWERS"
  assert_success
  assert_output --partial "Fetching from r2 FAILED"
  assert_equal "$(events | cut -d'|' -f1-4)" "list r2|copy r2 snapshot-20260301T000000Z.snap.gpg|list b2|copy b2 snapshot-20260101T000000Z.snap.gpg"
}

@test "an R2 bucket with no snapshot falls back to B2" {
  LIST_R2=$'notes.txt' run sh "$SCRIPT" "" "$OUT" <<< "$R2_ANSWERS"$'\n'"$B2_ANSWERS"
  assert_success
  assert_output --partial "r2 holds no snapshot"
}

@test "naming b2 never asks for R2's credential" {
  run sh "$SCRIPT" b2 "$OUT" <<< "$B2_ANSWERS"
  assert_success
  assert_equal "$(events | cut -d'|' -f1)" "list b2"
  run ! test -e "$CONFS/r2.conf"
}

@test "both providers failing fetches nothing and leaves no scratch directory" {
  FAIL_STEP=list-r2,list-b2 run -1 sh "$SCRIPT" "" "$OUT" <<< "$R2_ANSWERS"$'\n'"$B2_ANSWERS"
  assert_output --partial "No snapshot fetched."
  assert_equal "$(events)|$(test -e "$OUT" && echo present)|$(scratch_and_partial)" "list r2|list b2|agent killed|||"
}

@test "the secret half is read with echo off, is never an argument, and is written to a 0600 rclone.conf" {
  run sh "$SCRIPT" r2 "$OUT" <<< "$R2_ANSWERS"
  assert_success
  run ! grep -F R2SECRET "$CALLS"
  assert_equal "$(calls_to stty | tr '\n' '|')" "stty -echo|stty echo|stty echo|"
  assert_equal "$(cat "$CONFS/r2.mode")" "600"
  run awk '/^(access_key_id|secret_access_key|endpoint) / { print }' "$CONFS/r2.conf"
  assert_output "access_key_id = R2KEYID
secret_access_key = R2SECRET
endpoint = https://acct1.r2.cloudflarestorage.com"
}

@test "B2's endpoint and region come from the region typed" {
  run sh "$SCRIPT" b2 "$OUT" <<< "$B2_ANSWERS"
  assert_success
  run awk '/^(endpoint|region) / { print }' "$CONFS/b2.conf"
  assert_output "endpoint = https://s3.eu-central-003.backblazeb2.com
region = eu-central-003"
}

@test "an OUTPUT that exists is refused before anything is asked or called" {
  : > "$OUT"
  run -2 sh "$SCRIPT" r2 "$OUT" <<< "$R2_ANSWERS"
  assert_output --partial "exists"
  assert_equal "$(cat "$CALLS")|$(ls -A "$TMPDIR")" "|"
}

@test "an unknown provider is a usage error and touches nothing" {
  run -2 sh "$SCRIPT" gcs "$OUT"
  assert_output --partial "usage: snapshot-pull.sh [r2|b2] [OUTPUT]"
  assert_equal "$(cat "$CALLS")|$(ls -A "$TMPDIR")" "|"
}

@test "a failed key import leaves no output and no scratch directory" {
  FAIL_STEP=import run -2 sh "$SCRIPT" r2 "$OUT" <<< "$R2_ANSWERS"
  assert_equal "$(test -e "$OUT" && echo present)|$(scratch_and_partial)" "||"
}

@test "a failed decryption leaves no output, no partial file and no scratch directory" {
  FAIL_STEP=decrypt run -2 sh "$SCRIPT" r2 "$OUT" <<< "$R2_ANSWERS"
  assert_equal "$(test -e "$OUT" && echo present)|$(scratch_and_partial)" "||"
}

@test "a decrypted file that is not a snapshot is refused and removed" {
  DECRYPTED='plain text' run -1 sh "$SCRIPT" r2 "$OUT" <<< "$R2_ANSWERS"
  assert_output --partial "not a snapshot"
  assert_equal "$(test -e "$OUT" && echo present)|$(scratch_and_partial)" "||"
}
