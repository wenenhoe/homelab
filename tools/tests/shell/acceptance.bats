#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tofu/scratch/opnsense/acceptance/acceptance.sh)
  cp "$REPO_ROOT/tofu/scratch/opnsense/acceptance/stale_forward.yaml" "$(dirname "$SCRIPT")/"
  OUT="$BATS_TEST_TMPDIR/out"
  URL=https://mirror.example.net/releases/26.1/OPNsense-26.1.6-nano-amd64.img.bz2
  SUM=$(printf '0%.0s' $(seq 64))
  export NODE=root@pve PROXMOX_ENDPOINT=https://pve:8006/ PROXMOX_API_TOKEN='tofu@pve!t=token-secret' ANSIBLE_PLAYBOOK=ansible-playbook
  mkdir -p "$TEST_ROOT/ansible/roles/opnsense_gateway/defaults"
  printf 'opnsense_gateway_release: "26.1.11"\n' > "$TEST_ROOT/ansible/roles/opnsense_gateway/defaults/main.yaml"
  # The repo's own script is tested on its own; here it records the call and leaves what the real one leaves.
  cat > "$TEST_ROOT/tofu/scratch/opnsense/scratch_gateway.sh" <<'BODY'
#!/usr/bin/env bash
printf 'scratch_gateway %s WANT_VERSION=%s\n' "$1" "$WANT_VERSION" >> "$CALLS"
if [ "$1" = up ]; then
  mkdir -p "$2/first-boot"
  : > "$2/scratch.env"
  printf 'CERT\n' > "$2/first-boot/gateway-cert.pem"
  printf 'opnsense_root_password = "rootpw-1234"\nopnsense_root_otp_seed = "OTPSEED-1234"\nopnsense_api_key = "key-key-key-1"\nopnsense_api_secret = "API-SECRET-1"\n' > "$2/credentials.tfvars"
fi
BODY
  chmod +x "$TEST_ROOT/tofu/scratch/opnsense/scratch_gateway.sh"
  stub getent <<'BODY'
echo "${MGMT_ADDRESS:-127.0.0.1} OPNsense.internal"
BODY
  stub ansible-galaxy <<'BODY'
echo '{"/collections": {"oxlorg.opnsense": {"version": "26.1.11"}}}'
BODY
  # A stand-in for the node, answering by the command it is given, which is the last argument.
  stub ssh <<'BODY'
cmd=${*: -1}
case "$cmd" in
  "qm status "*) [ -n "${VM_EXISTS:-}" ] && echo "status: stopped" || exit 2 ;;
esac
BODY
  # A stand-in for the play: --check reports a change while a forward the play does not write is held,
  # and a run without --check removes it.
  stub ansible-playbook <<'BODY'
held=$BATS_TEST_TMPDIR/stale-forward
case " $* " in
  *" stale_forward.yaml "*) : > "$held" ;;
  *)
    if [ "${PLAY_FAIL:-}" = 1 ] && [[ " $* " != *" --check "* ]]; then
      echo "fatal: the play failed"
      exit 2
    fi
    if [[ " $* " == *" --check "* ]]; then
      if [ -e "$held" ] && [ -z "${CHECK_BLIND:-}" ]; then
        echo "localhost : ok=3 changed=1 unreachable=0 failed=0"
      else
        echo "localhost : ok=3 changed=0 unreachable=0 failed=0"
      fi
    elif [ -z "${NO_REMOVE:-}" ]; then
      rm -f "$held"
    fi
    ;;
esac
BODY
  # The two checks that talk to the gateway, and the one-line extra-vars writer.
  stub python3 <<'BODY'
case "$2" in
  -) printf '{}' > "$3" ;;
  */gui_login.py) echo "LOGIN the password alone is refused: PASS" ;;
  */api_scope.py)
    echo "API GET api/firewall/filter/get: PASS"
    [ -z "${LEAK:-}" ] || echo "API key was key-key-key-1"
    ;;
esac
BODY
}

teardown() {
  harness_teardown
}

@test "a run refuses an OUT_DIR inside the repository, before anything is built" {
  run ! "$SCRIPT" "$TEST_ROOT/out" "$URL" "$SUM"
  assert_output --partial "must be outside the repository"
  run calls_to scratch_gateway
  assert_output ""
}

@test "a run needs a management name that resolves to this machine, and says which line to add" {
  MGMT_ADDRESS=10.0.0.9 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "127.0.0.1 OPNsense.internal"
  run calls_to scratch_gateway
  assert_output ""
}

@test "a run refuses when the gateway's VM already exists" {
  VM_EXISTS=1 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "VM 501 exists"
  run calls_to scratch_gateway
  assert_output ""
}

@test "a run where every check passes ends successfully and removes the gateway" {
  run -0 "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "ALL CHECKS PASSED"
  assert_output --partial "CHECK the scratch gateway is removed: PASS"
  run calls_to scratch_gateway
  assert_line --index 0 "scratch_gateway up WANT_VERSION=26.1.11"
  assert_line --index 1 "scratch_gateway down WANT_VERSION=26.1.11"
}

@test "a play that fails still ends with the gateway removed and a failing status" {
  PLAY_FAIL=1 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "CHECK the play applies: FAIL"
  assert_output --partial "CHECK(S) FAILED"
  run calls_to scratch_gateway
  assert_line "scratch_gateway down WANT_VERSION=26.1.11"
}

@test "KEEP=1 leaves the gateway up and says how to remove it" {
  KEEP=1 run -0 "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "still up"
  run calls_to scratch_gateway
  refute_output --partial "down"
}

@test "a --check that does not report the forward the play does not write fails that check" {
  CHECK_BLIND=1 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "CHECK --check reports the forward the play does not write: FAIL"
}

@test "a forward that a run does not remove fails the check that follows" {
  NO_REMOVE=1 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "CHECK --check is clean again once it is removed: FAIL"
}

@test "a credential value in the results fails the run and names the file" {
  LEAK=1 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "A CREDENTIAL VALUE IS IN"
  assert_output --partial "api-scope.txt"
}
