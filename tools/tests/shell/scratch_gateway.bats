#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tofu/scratch/opnsense/scratch_gateway.sh)
  install_script tofu/scratch/opnsense/update_gateway.sh > /dev/null
  OUT="$BATS_TEST_TMPDIR/out"
  export NODE=root@pve PROXMOX_ENDPOINT=https://pve:8006/ PROXMOX_API_TOKEN='tofu@pve!t=token-secret' MIN_FREE_KB=1 GATE_TRIES=2 GATE_WAIT=0
  MOD="$TEST_ROOT/tofu/modules/proxmox_opnsense_vm"
  mkdir -p "$MOD/seed" "$MOD/first_boot"
  # The repo's own builder and first-boot script are tested on their own; here they record the call.
  cat > "$MOD/seed/build_seed.sh" <<'BODY'
#!/usr/bin/env bash
printf 'build_seed %s\n' "$*" >> "$CALLS"
out=$1
mkdir -p "$out"
: > "$out/seed.img"
while [ "$#" -gt 0 ]; do
  [ "$1" = --credentials ] && printf 'opnsense_root_password = "rootpw"\nopnsense_api_key = "KEY-1"\nopnsense_api_secret = "API-SECRET-1"\n' > "$2"
  shift
done
BODY
  cat > "$MOD/first_boot/first_boot.sh" <<'BODY'
#!/usr/bin/env bash
printf 'first_boot %s CREDENTIALS=%s\n' "$*" "$CREDENTIALS" >> "$CALLS"
mkdir -p "$2"
printf 'PEM\n' > "$2/gateway-cert.pem"
BODY
  chmod +x "$MOD/seed/build_seed.sh" "$MOD/first_boot/first_boot.sh"
  stub tofu <<'BODY'
case "$1" in
  apply)
    n=$(cat "$BATS_TEST_TMPDIR/apply.n" 2> /dev/null || echo 0)
    echo $((n + 1)) > "$BATS_TEST_TMPDIR/apply.n"
    [ "$((n + 1))" -gt "${APPLY_FAILS:-0}" ] || { echo "Error: VM create" >&2; exit 1; }
    ;;
  destroy) [ -z "${DESTROY_FAIL:-}" ] || exit 1 ;;
esac
env | grep '^TF_VAR_' | sed 's/^TF_VAR_proxmox_api_token=.*/TF_VAR_proxmox_api_token=<hidden>/' >> "$BATS_TEST_TMPDIR/tf-env"
BODY
  # The script only checks that bunzip2 is installed; the module unpacks the image, not this script.
  stub bunzip2 <<'BODY'
BODY
  stub scp <<'BODY'
BODY
  # A stand-in for the node, answering by the command it is given, which is the last argument.
  stub ssh <<'BODY'
mode=""
for a in "$@"; do
  case "$a" in -O) mode=control ;; -M) mode=master ;; esac
done
if [ -n "$mode" ]; then
  [ "$mode" = master ] && [ -n "${MASTER_FAIL:-}" ] && exit 255
  exit 0
fi
cmd=${*: -1}
case "$cmd" in
  "test -d /sys/class/net/"*) [ "${cmd##*/}" != "${BRIDGE_MISSING:-none}" ] ;;
  "ls /sys/class/net/"*) [ "$(echo "$cmd" | cut -d/ -f5)" != "${BRIDGE_PORTS:-none}" ] || echo tap100i0 ;;
  "qm status "*) [ -n "${VM_EXISTS:-}" ] && echo "status: stopped" || exit 2 ;;
  "pvesm list "*) [ -z "${LEFTOVER:-}" ] || echo "tofu-images:import/OPNsense-26.1.6-nano-amd64.raw" ;;
  "mktemp -d "*) echo /tmp/opn-scratch.TEST ;;
  "timeout 2 bash -c "*) [ -z "${GATE_DOWN:-}" ] ;;
  "SERIAL_SOCKET="*)
    echo "CHECK the gateway runs 26.1.11 after the update: PASS"
    [ -z "${UPDATE_FAIL:-}" ] || echo "CHECK the seed's API user works after the update: FAIL"
    ;;
esac
BODY
}

teardown() {
  harness_teardown
}

line_of() {
  grep -nF -m1 -- "$1" "$CALLS" | cut -d: -f1
}

@test "up needs the image URL and checksum" {
  run -1 "$SCRIPT" up "$OUT"
  assert_output --partial "up needs IMAGE_URL and IMAGE_CHECKSUM"
}

@test "up refuses a LAN bridge that does not exist, and says how to create it" {
  BRIDGE_MISSING=vmbr9 run -1 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  assert_output --partial "vmbr9 does not exist on the node"
  assert_output --partial "SDN.Use"
  run calls_to tofu
  refute_output --partial "apply"
}

@test "up refuses a LAN bridge that has ports" {
  BRIDGE_PORTS=vmbr9 run -1 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  assert_output --partial "vmbr9 has ports attached"
}

@test "up refuses the production WAN bridge and a WAN bridge equal to the LAN bridge" {
  WAN_BRIDGE=vmbr0 run -1 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  assert_output --partial "vmbr0 is the production WAN bridge"
  WAN_BRIDGE=vmbr9 run -1 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  assert_output --partial "must differ from the isolated LAN bridge"
}

@test "up refuses when the VM exists, and when files of an earlier run are stored" {
  VM_EXISTS=1 run -1 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  assert_output --partial "VM 501 exists"
  LEFTOVER=1 run -1 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  assert_output --partial "files from an earlier run are still stored"
}

@test "up refuses an OUT_DIR that already holds a scratch gateway or credentials" {
  mkdir -p "$OUT"
  : > "$OUT/scratch.env"
  run -1 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  assert_output --partial "Run down first"
  rm "$OUT/scratch.env"
  : > "$OUT/credentials.tfvars"
  run -1 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  assert_output --partial "use an empty OUT_DIR"
}

@test "up refuses when the free space is below the minimum" {
  MIN_FREE_KB=999999999999 run -1 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  assert_output --partial "less than 8 GB free"
}

@test "up builds the seed, applies, boots, updates and opens the tunnel, in that order" {
  run -0 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  [ "$(line_of build_seed)" -lt "$(line_of 'tofu apply')" ]
  [ "$(line_of 'tofu apply')" -lt "$(line_of first_boot)" ]
  [ "$(line_of first_boot)" -lt "$(line_of update_gateway.sh)" ]
  [ "$(line_of update_gateway.sh)" -lt "$(line_of '-O forward')" ]
  assert_output --partial "ansible-playbook playbooks/opnsense.yaml --check --diff"
  assert_output --partial "opnsense_gateway_ca_file=$OUT/first-boot/gateway-cert.pem"
}

@test "the seed and the boot use the scratch credentials file, never the real one" {
  run -0 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  run calls_to build_seed
  assert_output --partial "--credentials $OUT/credentials.tfvars"
  assert_output --partial "--lan-ip 192.168.77.1"
  run calls_to first_boot
  assert_output "first_boot 501 $OUT/first-boot CREDENTIALS=$OUT/credentials.tfvars"
}

@test "Tofu runs with the state and data in OUT_DIR, a read-only lock file and the stopped VM's inputs" {
  run -0 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  run calls_to tofu
  assert_output --partial "tofu init -backend=false -input=false -lockfile=readonly"
  assert_output --partial "-state=$OUT/terraform.tfstate"
  run cat "$BATS_TEST_TMPDIR/tf-env"
  assert_output --partial "TF_VAR_lan_bridge=vmbr9"
  assert_output --partial "TF_VAR_wan_bridge=vmbr1"
  assert_output --partial "TF_VAR_vm_id=501"
  assert_output --partial "TF_VAR_seed_image_path=$OUT/seed/seed.img"
  refute_output --partial "TF_VAR_wan_vlan_id"
}

@test "WAN_VLAN_ID and the bridges are passed on" {
  WAN_VLAN_ID=20 WAN_BRIDGE=vmbr2 LAN_BRIDGE=vmbr8 VM_ID=599 run -0 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  run cat "$BATS_TEST_TMPDIR/tf-env"
  assert_output --partial "TF_VAR_wan_vlan_id=20"
  assert_output --partial "TF_VAR_wan_bridge=vmbr2"
  assert_output --partial "TF_VAR_lan_bridge=vmbr8"
  assert_output --partial "TF_VAR_vm_id=599"
}

@test "a failed apply is retried, and three failures stop the run with the way to clean up" {
  APPLY_FAILS=2 run -0 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  run calls_to tofu
  assert_equal "$(echo "$output" | grep -c 'tofu apply')" 3
  rm -rf "$OUT" "$BATS_TEST_TMPDIR/apply.n"
  : > "$CALLS"
  APPLY_FAILS=5 run -1 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  assert_output --partial "run down to remove what it made"
  [ -f "$OUT/scratch.env" ]
  run calls_to first_boot
  assert_output ""
}

@test "no credential reaches a command line" {
  run -0 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  run cat "$CALLS"
  refute_output --partial "API-SECRET-1"
  refute_output --partial "KEY-1"
  refute_output --partial "token-secret"
  assert_equal "$(stat -c %a "$OUT/credentials.tfvars")" 600
}

@test "the update runs on the node with the pinned version, and a failed check stops the run before the tunnel" {
  run -0 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  run calls_to ssh
  assert_output --partial "update_gateway.sh\ /tmp/opn-scratch.TEST/gateway.env\ /tmp/opn-scratch.TEST/gateway-cert.pem\ 26.1.11\ "
  rm -rf "$OUT" "$BATS_TEST_TMPDIR/apply.n"
  : > "$CALLS"
  UPDATE_FAIL=1 run -1 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  assert_output --partial "the update reported failed checks"
  run grep -c -- '-O' "$CALLS"
  assert_output 0
}

@test "a gateway that does not answer on 443 stops the run with a pointer to the node's firewall" {
  GATE_DOWN=1 run -1 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  assert_output --partial "does not answer on TCP 443"
  run calls_to scp
  assert_output ""
}

@test "the tunnel uses the master connection given, or opens one of its own" {
  SSH_CONTROL_PATH=/tmp/given.sock run -0 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  run calls_to ssh
  assert_output --partial "-O forward -L 127.0.0.1:8443:192.168.77.1:443"
  refute_output --partial "-M"
  rm -rf "$OUT" "$BATS_TEST_TMPDIR/apply.n"
  : > "$CALLS"
  run -0 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  run calls_to ssh
  assert_output --partial "-M -S $OUT/tunnel.sock"
  grep -q '^own_master=1$' "$OUT/scratch.env"
}

@test "down closes the tunnel, destroys with the state in OUT_DIR, and removes what up left" {
  run -0 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  : > "$CALLS"
  run -0 "$SCRIPT" down "$OUT"
  assert_output "scratch gateway 501 removed"
  run calls_to ssh
  assert_output --partial "-O cancel -L 127.0.0.1:8443:192.168.77.1:443"
  assert_output --partial "-S $OUT/tunnel.sock -O exit"
  assert_output --partial "ip\ addr\ del\ 192.168.77.10/24\ dev\ vmbr9"
  assert_output --partial "rm\ -rf\ /tmp/opn-scratch.TEST"
  run calls_to tofu
  assert_output --partial "tofu destroy -auto-approve -input=false -state=$OUT/terraform.tfstate"
  [ ! -e "$OUT/scratch.env" ]
}

@test "down refuses an OUT_DIR with nothing recorded, and keeps the record when destroy fails" {
  run -1 "$SCRIPT" down "$OUT"
  assert_output --partial "nothing is recorded as up"
  run -0 "$SCRIPT" up "$OUT" http://x/y.bz2 abc
  DESTROY_FAIL=1 run -1 "$SCRIPT" down "$OUT"
  assert_output --partial "tofu destroy failed"
  [ -f "$OUT/scratch.env" ]
}
