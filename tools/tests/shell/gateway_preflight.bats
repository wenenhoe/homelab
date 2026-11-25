#!/usr/bin/env bats

VOLUME=tofu-images:import/OPNsense-26.1.6-nano-amd64.raw

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tools/rebuild_check/scripts/gateway_preflight.sh)
  export NODE=root@pve
  mkdir -p "$HOME/.config/tofu"
  : > "$HOME/.config/tofu/credentials.tfvars"
  export SEED="$BATS_TEST_TMPDIR/seed.img"
  : > "$SEED"
  # The node's answers, chosen by the command line the script sends. A test varies one with a variable.
  stub ssh <<'BODY'
cmd=${*: -1}
case "$cmd" in
  true)
    [ "${NODE_STATUS-0}" = 0 ] || { printf 'Permission denied (publickey,password).\n' >&2; exit 255; }
    ;;
  "pvesm list tofu-images --content import")
    printf 'Volid Format Type Size VMID\n'
    [ -z "${IMAGE_LISTED-$VOLUME}" ] || printf '%s raw import 3221225472\n' "${IMAGE_LISTED-$VOLUME}"
    ;;
  "qm config 201")
    [ "${VM_PRESENT-1}" = 1 ] || exit 2
    printf 'cores: 2\nname: %s\n' "${VM_NAME-OPNsense}"
    ;;
  "qm listsnapshot 201") exit "${SNAPSHOT_STATUS-0}" ;;
  "mountpoint -q /mnt/vzdump") exit "${MOUNT_STATUS-0}" ;;
  *"-size +0c")
    for _ in $(seq "${DUMPS_NONEMPTY-${DUMPS-0}}"); do printf '/mnt/vzdump/dump/vzdump-qemu-201-x.vma.zst\n'; done
    ;;
  "find /mnt/vzdump/dump "*)
    for _ in $(seq "${DUMPS-0}"); do printf '/mnt/vzdump/dump/vzdump-qemu-201-x.vma.zst\n'; done
    ;;
  "pveum user permissions tofu@pve --path /")
    [ "${GRANT_STATUS-0}" = 0 ] || exit 1
    printf '/ Sys.Audit\n'
    [ "${GRANT-0}" != 1 ] || printf '/ Sys.Modify\n'
    ;;
esac
BODY
  stub tofu <<'BODY'
[[ "$1" != -chdir=* ]] || shift
case "$1" in
  plan)
    printf 'STATE_MARK=%s\n' "${STATE_MARK-unset}" >> "$CALLS"
    [ "${PLAN_STATUS-0}" = 0 ] || { printf 'Error: backend unreachable\n'; exit 1; }
    ;;
  show) printf '{}\n' ;;
esac
BODY
  # rebuild_check.gateway_plan answers what the plan holds, rebuild_check.dns what the servers say.
  stub python3 <<'BODY'
case "$*" in
  *"gateway_plan verdict"*)
    printf '%s\n' "${VERDICT-the plan changes nothing}"
    exit "${VERDICT_STATUS-0}"
    ;;
  *"gateway_plan variable"*)
    [ -z "${VOLUME_MISSING-}" ] || exit 1
    printf '%s\n' "$VOLUME"
    ;;
  *"rebuild_check.dns --source-outside"*)
    [ "${SOURCE_STATUS-0}" = 0 ] || { printf 'OSError: Network is unreachable\n' >&2; exit 1; }
    [ -z "${OUTSIDE-}" ] || printf '%s\n' "$OUTSIDE"
    ;;
  *"rebuild_check.dns"*)
    printf 'FAIL  zones_have_one_serial  the secondary is behind\n\n1/2 checks passed\n'
    exit "${DNS_STATUS-0}"
    ;;
esac
BODY
  export VOLUME
}

teardown() {
  harness_teardown
}

calls_to_marker() {
  grep '^STATE_MARK=' "$CALLS" || true
}

@test "before: a clean gateway passes every check, notes the grant it is not holding, and changes nothing" {
  run -0 "$SCRIPT" before

  assert_line "ok    plan: the plan changes nothing"
  assert_line "ok    image: $VOLUME is on the node"
  assert_line "ok    vm: VM 201 is OPNsense"
  assert_line "ok    snapshots: the node lists VM 201's snapshots"
  assert_line "ok    dump: the storage is mounted and holds no dump of VM 201"
  assert_line "note  grant: tofu@pve does not hold Sys.Modify on /; the create needs it granted first"
  assert_line "ok    dns: both servers answer and agree"
  assert_line "all checks passed"
  run calls_to tofu
  assert_output --regexp "^tofu -chdir=[^ ]+/tofu plan -input=false -var-file=$HOME/.config/tofu/credentials.tfvars -out=[^ ]+/plan
tofu -chdir=[^ ]+/tofu show -json [^ ]+/plan$"
}

@test "before: a plan that changes something fails with what it changes, and the other checks still run" {
  VERDICT="the plan changes: module.ubuntu.vm (update)" VERDICT_STATUS=1 run -1 "$SCRIPT" before

  assert_line "FAIL  plan: the plan changes: module.ubuntu.vm (update)"
  assert_line "ok    vm: VM 201 is OPNsense"
  assert_line "1 check(s) failed"
}

@test "before: a plan that cannot be made fails with the end of tofu's output and reads no image volume" {
  PLAN_STATUS=1 run -1 "$SCRIPT" before

  assert_line "FAIL  plan: tofu plan failed; its last lines:"
  assert_line "        Error: backend unreachable"
  assert_line "FAIL  image: no plan to read the image volume from"
  run calls_to tofu
  assert_output --regexp "^tofu -chdir=[^ ]+/tofu plan "
}

@test "the state backend's environment is sourced for tofu when the file is readable" {
  printf 'STATE_MARK=encrypted\n' > "$HOME/.config/tofu/state-backend.env"
  run -0 "$SCRIPT" before

  run calls_to_marker
  assert_output "STATE_MARK=encrypted"
}

@test "a node that cannot be reached is one failure with ssh's own error, and no node check runs" {
  NODE_STATUS=255 run -1 "$SCRIPT" before

  assert_line --partial "FAIL  node: ssh to root@pve failed: Permission denied (publickey,password)."
  assert_line --partial "needs SSH_CONTROL_PATH"
  assert_line "FAIL  image: the node is not reachable"
  refute_output --partial "vm:"
  refute_output --partial "dump:"
  refute_output --partial "grant:"
  assert_line "ok    plan: the plan changes nothing"
  run calls_to ssh
  assert_output --regexp "^ssh -o BatchMode=yes -o ConnectTimeout=15 root@pve true$"
}

@test "an image volume the node does not list fails and says how to stage it" {
  IMAGE_LISTED=tofu-images:import/OPNsense-25.7-nano-amd64.raw run -1 "$SCRIPT" before

  assert_line "FAIL  image: $VOLUME is not on the node; stage it with tofu/scratch/opnsense/stage_image.sh"
}

@test "a plan that names no image volume fails the image check" {
  VOLUME_MISSING=1 run -1 "$SCRIPT" before

  assert_line "FAIL  image: the plan does not name the image volume"
}

@test "before: a VM 201 with another name, or none, fails" {
  VM_NAME=web run -1 "$SCRIPT" before
  assert_line "FAIL  vm: VM 201 is named 'web', not 'OPNsense'"

  VM_PRESENT=0 run -1 "$SCRIPT" before
  assert_line "FAIL  vm: there is no VM 201 on the node"
}

@test "before: a node that cannot list the VM's snapshots fails" {
  SNAPSHOT_STATUS=2 run -1 "$SCRIPT" before

  assert_line "FAIL  snapshots: the node could not list VM 201's snapshots"
}

@test "before: an unmounted dump storage fails and its dumps are not counted" {
  MOUNT_STATUS=1 run -1 "$SCRIPT" before

  assert_line "FAIL  dump: /mnt/vzdump is not a mount point on the node"
}

@test "before: an earlier dump of VM 201 fails, since dump would refuse it" {
  DUMPS=1 run -1 "$SCRIPT" before

  assert_line --partial "FAIL  dump: the storage already holds 1 dump(s) of VM 201, so dump would refuse"
}

@test "before: DNS servers that disagree fail with the end of the check's output" {
  DNS_STATUS=1 run -1 "$SCRIPT" before

  assert_line --partial "FAIL  dns: FAIL  zones_have_one_serial  the secondary is behind"
}

@test "before: a host outside the servers' zone asks no server, says where to run the check and still passes" {
  OUTSIDE=192.168.40.250 DNS_STATUS=1 run -0 "$SCRIPT" before

  assert_line "note  dns: not checked, since this host asks from 192.168.40.250, outside the services zone; on a services host run: cd tools && python3 -m rebuild_check.dns"
  assert_line "all checks passed"
  run calls_to python3
  refute_line "python3 -m rebuild_check.dns"
}

@test "before: a host whose source address cannot be told fails the dns check and asks no server" {
  SOURCE_STATUS=1 run -1 "$SCRIPT" before

  assert_line "FAIL  dns: could not tell which network this host asks from: OSError: Network is unreachable"
  run calls_to python3
  refute_line "python3 -m rebuild_check.dns"
}

@test "before: a grant that is already held is a note to revoke it, not a failure" {
  GRANT=1 run -0 "$SCRIPT" before

  assert_line "note  grant: tofu@pve already holds Sys.Modify on /; it is meant to be held only for the create"
}

@test "a grant that cannot be read fails in both stages" {
  GRANT_STATUS=1 run -1 "$SCRIPT" before
  assert_line "FAIL  grant: could not read tofu@pve's permissions on /"

  VM_PRESENT=0 DUMPS=1 GRANT_STATUS=1 run -1 "$SCRIPT" create
  assert_line "FAIL  grant: could not read tofu@pve's permissions on /"
}

@test "create: the planned additions, a gone VM, one dump and the grant pass, with the seed in the plan" {
  VERDICT="the plan adds the gateway VM and its seed file and nothing else" VM_PRESENT=0 DUMPS=1 GRANT=1 run -0 "$SCRIPT" create

  assert_line "ok    plan: the plan adds the gateway VM and its seed file and nothing else"
  assert_line "ok    vm: VM 201 is gone"
  assert_line "ok    dump: one dump of VM 201 is in the storage, the rollback"
  assert_line "ok    grant: tofu@pve holds Sys.Modify on /; revoke it after the create"
  assert_line "all checks passed"
  run calls_to tofu
  assert_output --partial "-var opnsense_seed_image_path=$SEED"
  # The create stage reads neither the snapshots nor DNS: the gateway they would ask is gone.
  run calls_to ssh
  refute_output --partial listsnapshot
  run calls_to python3
  refute_output --partial rebuild_check.dns
}

@test "create: a VM 201 that is still there fails" {
  DUMPS=1 GRANT=1 run -1 "$SCRIPT" create

  assert_line "FAIL  vm: VM 201 still exists on the node (named 'OPNsense'); a create under its VMID fails"
}

@test "create: no dump, an empty dump or two dumps fail, since the rollback must be one readable archive" {
  VM_PRESENT=0 GRANT=1 DUMPS=0 run -1 "$SCRIPT" create
  assert_line "FAIL  dump: expected one non-empty dump of VM 201 in /mnt/vzdump/dump, found 0 (0 non-empty)"

  VM_PRESENT=0 GRANT=1 DUMPS=1 DUMPS_NONEMPTY=0 run -1 "$SCRIPT" create
  assert_line "FAIL  dump: expected one non-empty dump of VM 201 in /mnt/vzdump/dump, found 1 (0 non-empty)"

  VM_PRESENT=0 GRANT=1 DUMPS=2 run -1 "$SCRIPT" create
  assert_line "FAIL  dump: expected one non-empty dump of VM 201 in /mnt/vzdump/dump, found 2 (2 non-empty)"
}

@test "create: a Tofu user without the startup privilege fails, since the create would be refused" {
  VM_PRESENT=0 DUMPS=1 run -1 "$SCRIPT" create

  assert_line "FAIL  grant: tofu@pve does not hold Sys.Modify on /, so the create fails with a 403; grant it first"
}

@test "create: a seed disk that is not readable fails the plan without running it" {
  SEED="$BATS_TEST_TMPDIR/missing.img" VM_PRESENT=0 DUMPS=1 GRANT=1 run -1 "$SCRIPT" create

  assert_line "FAIL  plan: the seed disk $BATS_TEST_TMPDIR/missing.img is not readable"
  run calls_to tofu
  assert_output ""
}

@test "a credentials file that is not readable fails the plan without running it" {
  CREDENTIALS="$BATS_TEST_TMPDIR/none.tfvars" run -1 "$SCRIPT" before

  assert_line "FAIL  plan: the credentials file $BATS_TEST_TMPDIR/none.tfvars is not readable"
  run calls_to tofu
  assert_output ""
}

@test "a missing or unknown stage is a usage error, and a missing NODE is refused" {
  run -2 "$SCRIPT"
  assert_output "usage: gateway_preflight.sh before | create"
  run -2 "$SCRIPT" later
  run -2 "$SCRIPT" before extra
  NODE='' run -1 "$SCRIPT" before
  assert_output --partial "set NODE to the ssh target of the Proxmox node"
}

@test "the temporary directory the plan is written to is removed on every exit" {
  run -1 env PLAN_STATUS=1 "$SCRIPT" before

  run find "$TMPDIR" -mindepth 1
  assert_output ""
}
