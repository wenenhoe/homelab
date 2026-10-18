#!/usr/bin/env bats

TEMPLATE=ansible/roles/caddy_cert_expiry/templates/check.sh.j2

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT="$TEST_ROOT/check.sh"
  render_template "$REPO_ROOT/$TEMPLATE" '{
    "caddy_cert_expiry_check_host": "app.example.test",
    "caddy_domain": "example.test",
    "caddy_cert_expiry_threshold_days": 30
  }' > "$SCRIPT"
  chmod +x "$SCRIPT"
  # The handshake succeeds, and the certificate it served ends at $NOT_AFTER;
  # with none set, x509 reads no certificate.
  stub openssl <<'BODY'
case "$1" in
  s_client) exit 0 ;;
  x509) [ -z "${NOT_AFTER:-}" ] || echo "notAfter=$NOT_AFTER" ;;
esac
BODY
}

teardown() {
  harness_teardown
}

# expires_in DURATION: a certificate end date, in the form openssl prints it,
# that far from now.
expires_in() {
  date -u -d "+$1" '+%b %e %H:%M:%S %Y GMT'
}

@test "a certificate with more than the threshold left passes" {
  NOT_AFTER=$(expires_in "40 days") run "$SCRIPT"
  assert_success
  assert_output --partial "app.example.test: certificate expires"
  assert_output --partial "(40 days left)"
}

@test "a certificate with exactly the threshold left passes" {
  NOT_AFTER=$(expires_in "30 days 12 hours") run "$SCRIPT"
  assert_success
  assert_output --partial "(30 days left)"
}

@test "a certificate with fewer days than the threshold left fails" {
  NOT_AFTER=$(expires_in "29 days 12 hours") run -1 "$SCRIPT"
  assert_output --partial "(29 days left)"
  assert_output --partial "Below the 30-day threshold"
}

@test "an expired certificate fails" {
  NOT_AFTER=$(expires_in "-2 days") run -1 "$SCRIPT"
  assert_output --partial "Below the 30-day threshold"
}

@test "no certificate on the wire fails" {
  run -1 "$SCRIPT"
  assert_output --partial "Could not read a certificate from app.example.test:443"
}

@test "the connection goes to loopback with the real hostname as the SNI" {
  NOT_AFTER=$(expires_in "40 days") run "$SCRIPT"
  assert_equal "$(calls_to openssl | head -1)" "openssl s_client -connect 127.0.0.1:443 -servername app.example.test"
}
