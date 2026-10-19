#!/usr/bin/env bats

TEMPLATE=ansible/roles/backup_agent/templates/check-freshness.sh.j2

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT="$TEST_ROOT/check-freshness.sh"
  ENV_FILES="$BATS_TEST_TMPDIR/env-files"
  : > "$ENV_FILES"
  export ENV_FILES
  # An app is told apart by the prefix it lists: `infra` fails to run, `stale`
  # has no object newer than its threshold, any other app has one. The env file
  # is read while the container "runs", as docker would read it.
  stub docker <<'BODY'
prev=
for arg in "$@"; do
  if [ "$prev" = --env-file ]; then
    {
      echo "path=$arg"
      echo "mode=$(stat -c %a "$arg")"
      grep -qx 'RCLONE_S3_SECRET_ACCESS_KEY=SECRETKEY' "$arg" && echo has-secret
    } >> "$ENV_FILES"
  fi
  prev=$arg
done
case "$*" in
  *":s3:b/h-infra/"*) echo boom >&2; exit 5 ;;
  *":s3:b/h-stale/"*) exit 0 ;;
  *) echo object.tar.gz ;;
esac
BODY
  # A push to Gatus is the one curl call that reads a config from stdin; CURL_FAIL
  # (kuma or gatus) makes that push fail with curl's HTTP error status.
  CURL_STDIN="$BATS_TEST_TMPDIR/curl-stdin"
  : > "$CURL_STDIN"
  export CURL_STDIN
  stub curl <<'BODY'
case " $* " in
  *" -K - "*) cat >> "$CURL_STDIN"; [ "${CURL_FAIL:-}" = gatus ] && exit 22 ;;
  *) [ "${CURL_FAIL:-}" = kuma ] && exit 22 ;;
esac
exit 0
BODY
}

teardown() {
  harness_teardown
}

# render_check PUSH_URL APP...: renders the template for host `h` with one
# schedule per app, 25 hours each, and makes the result executable. Host `h`'s
# Gatus endpoint is http://gatus/ep and its token GATUSTOKEN.
render_check() {
  local url=$1 schedules
  shift
  schedules=$(printf '{"app":"%s","freshness_hours":25},' "$@")
  render_template "$REPO_ROOT/$TEMPLATE" "$(printf '%s' '{
    "inventory_hostname": "h",
    "backup_agent_network_name": "net",
    "seaweedfs_s3_proto": "http",
    "seaweedfs_s3_endpoint": "s3:8333",
    "seaweedfs_s3_access_key": "ACCESSKEY",
    "seaweedfs_s3_secret_key": "SECRETKEY",
    "seaweedfs_s3_bucket": "b",
    "backup_agent_freshness_push_url": "'"$url"'",
    "heartbeat_push_urls": {"backup-h": "http://gatus/ep"},
    "heartbeat_job_tokens": {"backup-h": "GATUSTOKEN"},
    "backup_agent_schedules": ['"${schedules%,}"']
  }')" > "$SCRIPT"
  chmod +x "$SCRIPT"
}

@test "every app fresh: one push to Kuma's URL and one to Gatus" {
  render_check http://kuma/push/x one two
  run "$SCRIPT"
  assert_success
  assert_output --partial "every app on this host is fresh, pushing"
  assert_equal "$(calls_to curl)" "curl -fsS --max-time 10 http://kuma/push/x
curl -fsS --max-time 10 -K -"
}

@test "the Gatus push is a POST with the bearer token, and the token is not in an argument" {
  render_check http://kuma/push/x one two
  run "$SCRIPT"
  assert_success
  assert_equal "$(cat "$CURL_STDIN")" 'url = "http://gatus/ep"
request = "POST"
header = "Authorization: Bearer GATUSTOKEN"'
  run ! grep GATUSTOKEN "$CALLS"
}

@test "a failed Kuma push still pushes to Gatus and fails the unit" {
  render_check http://kuma/push/x one two
  CURL_FAIL=kuma run -1 "$SCRIPT"
  assert_equal "$(calls_to curl | wc -l)" 2
  assert_output --partial "every app on this host is fresh, pushing"
}

@test "a failed Gatus push fails the unit after Kuma's push went out" {
  render_check http://kuma/push/x one two
  CURL_FAIL=gatus run -1 "$SCRIPT"
  assert_equal "$(calls_to curl | head -n 1)" "curl -fsS --max-time 10 http://kuma/push/x"
  assert_equal "$(calls_to curl | wc -l)" 2
}

@test "one stale app suppresses both pushes without failing" {
  render_check http://kuma/push/x one stale
  run "$SCRIPT"
  assert_success
  assert_output --partial "stale: no backup newer than 25h found (not an error)"
  assert_output --partial "not pushing"
  assert_equal "$(calls_to curl)" ""
}

@test "an rclone failure suppresses the push and fails, naming the app and the error" {
  render_check http://kuma/push/x one infra
  run -1 "$SCRIPT"
  assert_output --partial "infra: rclone failed (exit 5): boom"
  assert_equal "$(calls_to curl)" ""
}

@test "a failure and a stale app together still fail" {
  render_check http://kuma/push/x stale infra
  run -1 "$SCRIPT"
  assert_equal "$(calls_to curl)" ""
}

@test "with no Kuma push URL every app is still checked and only Gatus is pushed" {
  render_check "" one two
  run "$SCRIPT"
  assert_success
  assert_output --partial "no Uptime Kuma push URL configured yet for this host"
  assert_equal "$(calls_to docker | wc -l)" 2
  assert_equal "$(calls_to curl)" "curl -fsS --max-time 10 -K -"
}

@test "with a stale app and no Kuma push URL nothing is pushed" {
  render_check "" one stale
  run "$SCRIPT"
  assert_success
  assert_equal "$(calls_to curl)" ""
}

@test "the credentials go in a 0600 env file that is removed afterwards, and not in an argument" {
  render_check http://kuma/push/x one stale infra
  run -1 "$SCRIPT"
  # One env file per app, each read at mode 600 with the secret in it.
  assert_equal "$(grep -c '^mode=600$' "$ENV_FILES")" 3
  assert_equal "$(grep -c '^has-secret$' "$ENV_FILES")" 3
  while read -r path; do
    [ ! -e "$path" ]
  done < <(sed -n 's/^path=//p' "$ENV_FILES")
  run ! grep -e SECRETKEY -e ACCESSKEY "$CALLS"
  # The stderr capture is removed too.
  assert_equal "$(ls -A "$TMPDIR")" ""
}

@test "the list runs in the app's network without capabilities" {
  render_check "" one
  run "$SCRIPT"
  assert_success
  run grep -e '--network net ' -e '--cap-drop ALL' -e '--security-opt no-new-privileges:true' -e ' lsf :s3:b/h-one/ --max-age 25h --files-only' "$CALLS"
  assert_equal "${#lines[@]}" 1
}

@test "a host with no Gatus job fails the render instead of skipping the push" {
  run -1 render_template "$REPO_ROOT/$TEMPLATE" "$(printf '%s' '{
    "inventory_hostname": "h",
    "backup_agent_network_name": "net",
    "seaweedfs_s3_proto": "http",
    "seaweedfs_s3_endpoint": "s3:8333",
    "seaweedfs_s3_access_key": "ACCESSKEY",
    "seaweedfs_s3_secret_key": "SECRETKEY",
    "seaweedfs_s3_bucket": "b",
    "backup_agent_freshness_push_url": "",
    "heartbeat_push_urls": {},
    "heartbeat_job_tokens": {},
    "backup_agent_schedules": []
  }')"
  assert_output --partial "no attribute 'backup-h'"
}

@test "a variable the template needs and the test leaves out fails the render" {
  run -1 render_template "$REPO_ROOT/$TEMPLATE" '{"inventory_hostname":"h"}'
  assert_output --partial "is undefined"
}
