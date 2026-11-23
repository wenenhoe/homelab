#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tools/rebuild_check/scripts/move_vm_nic.sh)
  export QM_NAME=operator QM_NET='virtio=BC:24:11:00:C9:40,bridge=vmbr1,firewall=1,tag=25'
  # `qm config` of a VMID with no VM fails; a NIC the VM lacks is not printed.
  stub qm <<'BODY'
case "$1" in
  config)
    [ -z "${QM_MISSING-}" ] || exit 2
    printf 'cores: 2\nname: %s\n' "$QM_NAME"
    [ -z "$QM_NET" ] || printf 'net0: %s\n' "$QM_NET"
    [ -z "${QM_NET1-}" ] || printf 'net1: %s\n' "$QM_NET1"
    printf 'memory: 2048\n'
    ;;
  set) true ;;
esac
BODY
}

teardown() {
  harness_teardown
}

@test "moving to an untagged bridge keeps the model and MAC, drops the tag and says the line before and after" {
  run -0 "$SCRIPT" 401 operator net0 vmbr0 none

  assert_line "net0 of VM 401 was: virtio=BC:24:11:00:C9:40,bridge=vmbr1,firewall=1,tag=25"
  assert_line "net0 of VM 401 is now: virtio=BC:24:11:00:C9:40,bridge=vmbr0,firewall=1"
  run calls_to qm
  assert_output - <<'LOG'
qm config 401
qm set 401 --net0 virtio=BC:24:11:00:C9:40\,bridge=vmbr0\,firewall=1
LOG
}

@test "a tag is set on the NIC when one is given, replacing the old one" {
  run -0 "$SCRIPT" 401 operator net0 vmbr1 40

  assert_line "net0 of VM 401 is now: virtio=BC:24:11:00:C9:40,bridge=vmbr1,firewall=1,tag=40"
}

@test "an untagged NIC given a tag gets it after its other options" {
  QM_NET='virtio=BC:24:11:00:C9:40,bridge=vmbr0' run -0 "$SCRIPT" 401 operator net0 vmbr1 25

  assert_line "net0 of VM 401 is now: virtio=BC:24:11:00:C9:40,bridge=vmbr1,tag=25"
}

@test "another NIC of the VM is the one moved when it is named" {
  QM_NET1='virtio=BC:24:11:00:C9:41,bridge=vmbr1' run -0 "$SCRIPT" 401 operator net1 vmbr0 none

  assert_line "net1 of VM 401 was: virtio=BC:24:11:00:C9:41,bridge=vmbr1"
  assert_line "net1 of VM 401 is now: virtio=BC:24:11:00:C9:41,bridge=vmbr0"
}

@test "a VM whose name differs is not touched" {
  run -1 "$SCRIPT" 401 gateway net0 vmbr0 none

  assert_output "VM 401 is named 'operator', not 'gateway'"
  run calls_to qm
  assert_output "qm config 401"
}

@test "a VMID with no VM fails before anything is set" {
  QM_MISSING=1 run -1 "$SCRIPT" 401 operator net0 vmbr0 none

  assert_output "no VM 401"
  run calls_to qm
  assert_output "qm config 401"
}

@test "a NIC the VM does not have fails before anything is set" {
  QM_NET='' run -1 "$SCRIPT" 401 operator net0 vmbr0 none

  assert_output "VM 401 has no net0"
  run calls_to qm
  assert_output "qm config 401"
}

@test "a NIC that names no bridge fails before anything is set" {
  QM_NET='virtio=BC:24:11:00:C9:40' run -1 "$SCRIPT" 401 operator net0 vmbr0 none

  assert_output "net0 of VM 401 names no bridge: virtio=BC:24:11:00:C9:40"
  run calls_to qm
  assert_output "qm config 401"
}

@test "arguments that are missing or malformed are a usage error and call nothing" {
  run -2 "$SCRIPT" 401 operator net0 vmbr0
  assert_output "usage: bash -s -- VMID NAME NET BRIDGE TAG|none"
  run -2 "$SCRIPT" 4o1 operator net0 vmbr0 none
  run -2 "$SCRIPT" 401 operator eth0 vmbr0 none
  run -2 "$SCRIPT" 401 operator net0 'vmbr0;reboot' none
  run -2 "$SCRIPT" 401 operator net0 vmbr0 vlan25
  run calls_to qm
  assert_output ""
}
