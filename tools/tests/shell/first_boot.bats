#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tofu/modules/proxmox_opnsense_vm/first_boot/first_boot.sh)
  OUT="$BATS_TEST_TMPDIR/out"
  export NODE=root@pve
  export CREDENTIALS="$BATS_TEST_TMPDIR/credentials.tfvars"
  printf 'proxmox_endpoint = "https://pve:8006/"\nopnsense_root_password = "seed-root-pw"\n' > "$CREDENTIALS"
  # What the node holds after the driver ran, which the stub ssh serves for `cat`.
  NODE_FILES="$BATS_TEST_TMPDIR/node"
  export NODE_FILES DRIVER_STDIN="$BATS_TEST_TMPDIR/driver.stdin"
  mkdir -p "$NODE_FILES"
  printf 'transcript\n' > "$NODE_FILES/console.log"
  printf '{"result": "done"}\n' > "$NODE_FILES/result.json"
  printf 'PEM\n' > "$NODE_FILES/gateway-cert.pem"
  # A stand-in for the node: it answers by the command it is given, which is the last argument.
  stub ssh <<'BODY'
cmd=${*: -1}
case "$cmd" in
  "qm status "*) echo "status: ${VM_STATUS:-stopped}" ;;
  "mktemp -d "*) echo /tmp/opn-first-boot.TEST ;;
  "python3 -I "*) cat > "$DRIVER_STDIN"; exit "${DRIVER_RC:-0}" ;;
  "cat /tmp/opn-first-boot.TEST/"*) cat "$NODE_FILES/${cmd##*/}" ;;
esac
BODY
  stub scp <<'BODY'
BODY
}

teardown() {
  harness_teardown
}

# The call log records each argument shell-quoted, so a space inside one reads as "\ ".
line_of() {
  grep -nF -m1 -- "$1" "$CALLS" | cut -d: -f1
}

@test "the driver is copied to the node first, then the VM is started, then the driver runs" {
  run -0 "$SCRIPT" 501 "$OUT"
  run calls_to scp
  assert_output --regexp "^scp -q .* /.*/import_seed\.py root@pve:/tmp/opn-first-boot\.TEST/$"
  [ "$(line_of 'scp ')" -lt "$(line_of 'qm\ start\ 501')" ]
  [ "$(line_of 'qm\ start\ 501')" -lt "$(line_of 'python3\ -I')" ]
}

@test "the driver gets the VM's serial socket and the seed disk, and the password on stdin only" {
  run -0 "$SCRIPT" 501 "$OUT"
  assert_equal "$(cat "$DRIVER_STDIN")" "seed-root-pw"
  run calls_to ssh
  assert_output --partial 'import_seed.py\ --socket\ /var/run/qemu-server/501.serial0\ --seed-disk\ da1\ '
  refute_output --partial "seed-root-pw"
}

@test "SEED_DISK names another seed disk" {
  SEED_DISK=da2 run -0 "$SCRIPT" 501 "$OUT"
  run calls_to ssh
  assert_output --partial '\ --seed-disk\ da2\ '
}

@test "the transcript, result and certificate are brought back" {
  run -0 "$SCRIPT" 501 "$OUT"
  assert_equal "$(cat "$OUT/console.log")" "transcript"
  assert_equal "$(cat "$OUT/result.json")" '{"result": "done"}'
  assert_equal "$(cat "$OUT/gateway-cert.pem")" "PEM"
  assert_output "gateway certificate: $OUT/gateway-cert.pem"
}

@test "a driver that fails passes its exit status on and brings back what exists, without a certificate" {
  rm "$NODE_FILES/gateway-cert.pem"
  DRIVER_RC=5 run -5 "$SCRIPT" 501 "$OUT"
  assert_output --partial "importer driver exited 5"
  [ -f "$OUT/console.log" ]
  [ ! -e "$OUT/gateway-cert.pem" ]
}

@test "a certificate from an earlier run is not left beside the result of a failed one" {
  mkdir -p "$OUT"
  printf 'old PEM\n' > "$OUT/gateway-cert.pem"
  rm "$NODE_FILES/gateway-cert.pem"
  DRIVER_RC=2 run -2 "$SCRIPT" 501 "$OUT"
  [ ! -e "$OUT/gateway-cert.pem" ]
}

@test "the scratch directory on the node is removed after a success and after a failure" {
  run -0 "$SCRIPT" 501 "$OUT"
  run calls_to ssh
  assert_output --partial 'rm\ -rf\ /tmp/opn-first-boot.TEST'
  : > "$CALLS"
  DRIVER_RC=3 run -3 "$SCRIPT" 501 "$OUT"
  run calls_to ssh
  assert_output --partial 'rm\ -rf\ /tmp/opn-first-boot.TEST'
}

@test "a VM that is not stopped is refused before it is touched" {
  VM_STATUS=running run -1 "$SCRIPT" 501 "$OUT"
  assert_output --partial "VM 501 is not stopped (status: running)"
  run calls_to ssh
  refute_output --partial 'qm\ start'
  [ -z "$(calls_to scp)" ]
}

@test "credentials without the root password stop the script before any ssh call" {
  printf 'proxmox_endpoint = "https://pve:8006/"\n' > "$CREDENTIALS"
  run -1 "$SCRIPT" 501 "$OUT"
  assert_output --partial "holds no opnsense_root_password"
  [ -z "$(calls_to ssh)" ]
}

@test "a password in the output removes it and fails the run" {
  printf 'login with seed-root-pw\n' > "$NODE_FILES/console.log"
  run -1 "$SCRIPT" 501 "$OUT"
  assert_output --partial "root password was found in the output"
  [ ! -e "$OUT/console.log" ]
  [ ! -e "$OUT/result.json" ]
  [ ! -e "$OUT/gateway-cert.pem" ]
}

@test "an ssh master connection is used when SSH_CONTROL_PATH names one" {
  SSH_CONTROL_PATH=/tmp/opn-ssh.sock run -0 "$SCRIPT" 501 "$OUT"
  run calls_to ssh
  assert_output --partial "ControlPath=/tmp/opn-ssh.sock"
  run calls_to scp
  assert_output --partial "ControlPath=/tmp/opn-ssh.sock"
}

@test "ssh never asks for a password itself" {
  run -0 "$SCRIPT" 501 "$OUT"
  run calls_to ssh
  assert_output --partial "BatchMode=yes"
}

@test "the node is required" {
  unset NODE
  run -1 "$SCRIPT" 501 "$OUT"
  assert_output --partial "set NODE"
}
