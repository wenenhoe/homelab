#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tofu/scratch/opnsense/acceptance/acceptance.sh)
  cp "$REPO_ROOT/tofu/scratch/opnsense/acceptance/stale_forward.yaml" "$REPO_ROOT/tofu/scratch/opnsense/acceptance/stray_rule.yaml" "$REPO_ROOT/tofu/scratch/opnsense/acceptance/management_reach.py" "$(dirname "$SCRIPT")/"
  OUT="$BATS_TEST_TMPDIR/out"
  URL=https://mirror.example.net/releases/26.1/OPNsense-26.1.6-nano-amd64.img.bz2
  SUM=$(printf '0%.0s' $(seq 64))
  export NODE=root@pve PROXMOX_ENDPOINT=https://pve:8006/ PROXMOX_API_TOKEN='tofu@pve!t=token-secret' ANSIBLE_PLAYBOOK=ansible-playbook
  mkdir -p "$TEST_ROOT/ansible/roles/opnsense_gateway/defaults"
  printf 'opnsense_gateway_release: "26.1.11"\nopnsense_gateway_zones:\n  - { name: desktops, vlan: 40, interface: opt5, internet: true, dhcp: true }\n' > "$TEST_ROOT/ansible/roles/opnsense_gateway/defaults/main.yaml"
  # The repo's own script is tested on its own; here it records the call and leaves what the real one leaves.
  cat > "$TEST_ROOT/tofu/scratch/opnsense/scratch_gateway.sh" <<'BODY'
#!/usr/bin/env bash
printf 'scratch_gateway %s WANT_VERSION=%s\n' "$1" "$WANT_VERSION" >> "$CALLS"
[ "$1" != down ] || [ -z "${DOWN_FAIL:-}" ] || exit 1
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
  "python3 - "*)
    if [ -n "${REACH_FAIL:-}" ]; then
      echo "REACH another address on the LAN does not reach the GUI and API port: FAIL"
      exit 1
    fi
    echo "REACH another address on the LAN does not reach the GUI and API port: PASS"
    ;;
esac
BODY
  # A stand-in for the play: --check reports a change while a forward or a rule the play does not write is held,
  # and a run without --check removes it, naming the rule it removed as the play's loop does.
  stub ansible-playbook <<'BODY'
held=$BATS_TEST_TMPDIR/stale-forward
held_rule=$BATS_TEST_TMPDIR/stray-rule
case " $* " in
  *" stale_forward.yaml "*) : > "$held" ;;
  *" stray_rule.yaml "*)
    : > "$held_rule"
    printf '%s\n' "$*" > "$BATS_TEST_TMPDIR/stray-args"
    ;;
  *)
    if [ "${PLAY_FAIL:-}" = 1 ] && [[ " $* " != *" --check "* ]]; then
      echo "fatal: the play failed"
      exit 2
    fi
    if [[ " $* " == *" --check "* ]]; then
      if [ -e "$held" ] && [ -z "${CHECK_BLIND:-}" ]; then
        echo "localhost : ok=3 changed=1 unreachable=0 failed=0"
      elif [ -e "$held_rule" ] && [ -z "${RULE_CHECK_BLIND:-}" ]; then
        echo "changed: [localhost] => (item=scratch acceptance: a rule the play does not write)"
        echo "localhost : ok=3 changed=1 unreachable=0 failed=0"
      else
        echo "localhost : ok=3 changed=0 unreachable=0 failed=0"
      fi
    elif [ -z "${NO_REMOVE:-}" ]; then
      if [ -e "$held_rule" ]; then
        echo "changed: [localhost] => (item=scratch acceptance: a rule the play does not write)"
        [ -z "${GUARD_REMOVED:-}" ] || echo "changed: [localhost] => (item=guard: operator hosts to the gateway's management ports)"
      fi
      rm -f "$held" "$held_rule"
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

@test "a gateway that cannot be removed fails the run, and the summary does not claim every check passed" {
  DOWN_FAIL=1 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "CHECK the scratch gateway is removed: FAIL"
  assert_output --partial "1 CHECK(S) FAILED"
  refute_output --partial "ALL CHECKS PASSED"
}

@test "a gateway that cannot be removed after an earlier failure is tried once" {
  PLAY_FAIL=1 DOWN_FAIL=1 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  run calls_to scratch_gateway
  assert_equal "$(grep -c '^scratch_gateway down' <<< "$output")" 1
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

@test "the stray rule is added on the interface the role's list gives the desktops zone" {
  run -0 "$SCRIPT" "$OUT" "$URL" "$SUM"
  run cat "$BATS_TEST_TMPDIR/stray-args"
  assert_output --partial "-e interface=opt5"
}

@test "a --check that does not report the rule the play does not write fails that check" {
  RULE_CHECK_BLIND=1 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "CHECK --check reports the rule the play does not write: FAIL"
}

@test "a rule that a run does not remove fails the checks that follow" {
  NO_REMOVE=1 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "CHECK the run removed that rule: FAIL"
  assert_output --partial "CHECK --check is clean again once the rule is removed: FAIL"
}

@test "a run that removes the guard rule fails the run" {
  GUARD_REMOVED=1 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "CHECK the guard rule is not among the rules the run removed: FAIL"
}

@test "a credential value in the results fails the run and names the file" {
  LEAK=1 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "A CREDENTIAL VALUE IS IN"
  assert_output --partial "api-scope.txt"
}

@test "the probe address is added to the node's LAN bridge and removed again when every check passes" {
  run -0 "$SCRIPT" "$OUT" "$URL" "$SUM"
  run calls_to ssh
  assert_output --partial "ip\\ addr\\ add\\ 192.168.77.11/24\\ dev\\ vmbr9"
  assert_output --partial "ip\\ addr\\ del\\ 192.168.77.11/24\\ dev\\ vmbr9"
}

@test "a management port that another LAN address reaches fails the run, and the probe address is still removed" {
  REACH_FAIL=1 run ! "$SCRIPT" "$OUT" "$URL" "$SUM"
  assert_output --partial "CHECK only the admitted address reaches the GUI and API port, and no address reaches SSH: FAIL"
  run calls_to ssh
  assert_output --partial "ip\\ addr\\ del\\ 192.168.77.11/24\\ dev\\ vmbr9"
}

@test "KEEP=1 still removes the probe address from the node's bridge" {
  KEEP=1 run -0 "$SCRIPT" "$OUT" "$URL" "$SUM"
  run calls_to ssh
  assert_output --partial "ip\\ addr\\ del\\ 192.168.77.11/24\\ dev\\ vmbr9"
}
