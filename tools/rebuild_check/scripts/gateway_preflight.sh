#!/usr/bin/env bash
# Read-only checks before the production gateway (VM 201) is rebuilt. Runs on the operator host with the
# credentials Tofu uses, and changes nothing on the node, in Tofu's state or in the repository.
# Usage: gateway_preflight.sh before | create
#   before  the window is not open and the old gateway still runs: the root module plans no change, the
#           image is on the node, VM 201 is the gateway and can be snapshotted, nothing in the dump storage
#           would stop the dump, and both DNS servers answer and agree (noted and not checked on a host
#           outside the servers' zone, which the gateway denies direct DNS)
#   create  the old VM is dumped and destroyed and the create is next: the plan adds the gateway VM and its
#           seed file and nothing else, the image is on the node, VM 201 is gone, the dump is there to roll
#           back to, and the Tofu user holds the privilege a startup order needs
# It prints one line per check, `ok`, `note` (a fact for a person to act on) or `FAIL`, and exits 1 when any
# check fails.
# Environment: NODE (ssh target of the Proxmox node), CREDENTIALS (default ~/.config/tofu/credentials.tfvars),
#   STATE_ENV (default ~/.config/tofu/state-backend.env, sourced when readable: Tofu's state backend and
#   encryption settings, which any tofu command on the root module needs; the checkout must have had `tofu init`),
#   SEED (default ~/opnsense-seed/seed.img, create only), VM_ID (default 201), GATEWAY_NAME (default
#   OPNsense), TOFU_USER (default tofu@pve), DUMP_DIR (default /mnt/vzdump), TOFU (default tofu),
#   SSH_CONTROL_PATH (socket of an ssh master connection opened by hand, for a node that takes a password).
set -euo pipefail

usage="usage: gateway_preflight.sh before | create"
stage=${1:-}
case "$stage" in
  before | create) [ "$#" -eq 1 ] || {
    echo "$usage" >&2
    exit 2
  } ;;
  *)
    echo "$usage" >&2
    exit 2
    ;;
esac
: "${NODE:?set NODE to the ssh target of the Proxmox node}"

here=$(cd "$(dirname "$0")" && pwd)
tools=$(cd "$here/../.." && pwd)
repo=$(cd "$tools/.." && pwd)
vmid=${VM_ID:-201}
gateway_name=${GATEWAY_NAME:-OPNsense}
tofu_user=${TOFU_USER:-tofu@pve}
dump_dir=${DUMP_DIR:-/mnt/vzdump}
archive_dir=$dump_dir/dump
credentials=${CREDENTIALS:-$HOME/.config/tofu/credentials.tfvars}
seed=${SEED:-$HOME/opnsense-seed/seed.img}
tofu=${TOFU:-tofu}
state_env=${STATE_ENV:-$HOME/.config/tofu/state-backend.env}
if [ -r "$state_env" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$state_env"
  set +a
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
failed=0
ok() { printf 'ok    %s\n' "$*"; }
note() { printf 'note  %s\n' "$*"; }
bad() {
  printf 'FAIL  %s\n' "$*"
  failed=$((failed + 1))
}

ssh_opts=(-o BatchMode=yes -o ConnectTimeout=15)
[ -z "${SSH_CONTROL_PATH:-}" ] || ssh_opts+=(-o "ControlPath=$SSH_CONTROL_PATH")
# The remote command is built here on purpose: the VMID and paths are expanded on this side.
# shellcheck disable=SC2029
node() { ssh "${ssh_opts[@]}" "$NODE" "$@"; }
plan_tool() { (cd "$tools" && python3 -m rebuild_check.gateway_plan "$@"); }

# The plan of the root module, read as JSON. The create stage plans with the seed, as the apply will.
check_plan() {
  local plan_args=(-input=false -var-file="$credentials" -out="$work/plan") message
  if [ ! -r "$credentials" ]; then
    bad "plan: the credentials file $credentials is not readable"
    return
  fi
  if [ "$stage" = create ]; then
    if [ ! -r "$seed" ]; then
      bad "plan: the seed disk $seed is not readable"
      return
    fi
    plan_args+=(-var "opnsense_seed_image_path=$seed")
  fi
  if ! "$tofu" -chdir="$repo/tofu" plan "${plan_args[@]}" > "$work/plan.log" 2>&1; then
    bad "plan: tofu plan failed; its last lines:"
    tail -n 15 "$work/plan.log" | sed 's/^[│╷╵ ]*/        /'
    return
  fi
  "$tofu" -chdir="$repo/tofu" show -json "$work/plan" > "$work/plan.json"
  if message=$(plan_tool verdict "$stage" "$work/plan.json"); then
    ok "plan: $message"
  else
    bad "plan: $message"
  fi
}

# The image the root module imports the system disk from has to be on the node before a create.
check_image() {
  local volume listing
  if ! volume=$(plan_tool variable opnsense_image_volume_id "$work/plan.json" 2> /dev/null); then
    bad "image: the plan does not name the image volume"
    return
  fi
  if ! listing=$(node "pvesm list ${volume%%:*} --content import"); then
    bad "image: could not list the import content of ${volume%%:*} on the node"
    return
  fi
  if awk -v volume="$volume" '$1 == volume {found = 1} END {exit !found}' <<< "$listing"; then
    ok "image: $volume is on the node"
  else
    bad "image: $volume is not on the node; stage it with tofu/scratch/opnsense/stage_image.sh"
  fi
}

check_vm() {
  local config name
  if config=$(node "qm config $vmid" 2> /dev/null); then
    name=$(awk -F': ' '$1 == "name" {print $2}' <<< "$config")
    if [ "$stage" = create ]; then
      bad "vm: VM $vmid still exists on the node (named '$name'); a create under its VMID fails"
    elif [ "$name" = "$gateway_name" ]; then
      ok "vm: VM $vmid is $gateway_name"
    else
      bad "vm: VM $vmid is named '$name', not '$gateway_name'"
    fi
  elif [ "$stage" = create ]; then
    ok "vm: VM $vmid is gone"
  else
    bad "vm: there is no VM $vmid on the node"
  fi
}

# The snapshots of the rebuild are taken on the node with qm, so the node has to answer for this VM.
check_snapshots() {
  if node "qm listsnapshot $vmid" > /dev/null 2>&1; then
    ok "snapshots: the node lists VM $vmid's snapshots"
  else
    bad "snapshots: the node could not list VM $vmid's snapshots"
  fi
}

# retire_vm.sh refuses a dump when one exists and a destroy without one, so the window must find the
# storage mounted and the dump absent before the dump and there after it.
check_dump() {
  local all nonempty
  if ! node "mountpoint -q $dump_dir" 2> /dev/null; then
    bad "dump: $dump_dir is not a mount point on the node"
    return
  fi
  all=$(node "find $archive_dir -maxdepth 1 -name 'vzdump-qemu-$vmid-*.vma.zst'" 2> /dev/null | grep -c . || true)
  nonempty=$(node "find $archive_dir -maxdepth 1 -name 'vzdump-qemu-$vmid-*.vma.zst' -size +0c" 2> /dev/null | grep -c . || true)
  if [ "$stage" = before ]; then
    if [ "$all" -eq 0 ]; then
      ok "dump: the storage is mounted and holds no dump of VM $vmid"
    else
      bad "dump: the storage already holds $all dump(s) of VM $vmid, so dump would refuse; drop an earlier one only once it is not a rollback"
    fi
  elif [ "$all" -eq 1 ] && [ "$nonempty" -eq 1 ]; then
    ok "dump: one dump of VM $vmid is in the storage, the rollback"
  else
    bad "dump: expected one non-empty dump of VM $vmid in $archive_dir, found $all ($nonempty non-empty)"
  fi
}

# A startup order needs Sys.Modify on /, which the Tofu user holds only between the grant and its revoke.
check_grant() {
  local permissions
  if ! permissions=$(node "pveum user permissions $tofu_user --path /" 2> /dev/null); then
    bad "grant: could not read $tofu_user's permissions on /"
    return
  fi
  if grep -q 'Sys.Modify' <<< "$permissions"; then
    if [ "$stage" = create ]; then
      ok "grant: $tofu_user holds Sys.Modify on /; revoke it after the create"
    else
      note "grant: $tofu_user already holds Sys.Modify on /; it is meant to be held only for the create"
    fi
  elif [ "$stage" = create ]; then
    bad "grant: $tofu_user does not hold Sys.Modify on /, so the create fails with a 403; grant it first"
  else
    note "grant: $tofu_user does not hold Sys.Modify on /; the create needs it granted first"
  fi
}

# The gateway denies direct DNS from other zones, so only a host in the servers' zone can ask them.
check_dns() {
  local outside
  if ! outside=$(cd "$tools" && python3 -m rebuild_check.dns --source-outside 2> "$work/dns.log"); then
    bad "dns: could not tell which network this host asks from: $(tail -n 1 "$work/dns.log")"
  elif [ -n "$outside" ]; then
    note "dns: not checked, since this host asks from $outside, outside the services zone; on a services host run: cd tools && python3 -m rebuild_check.dns"
  elif (cd "$tools" && python3 -m rebuild_check.dns) > "$work/dns.log" 2>&1; then
    ok "dns: both servers answer and agree"
  else
    bad "dns: $(tail -n 3 "$work/dns.log" | tr '\n' ' ')"
  fi
}

# Every other check reads the node, so a node that cannot be reached is said once, with ssh's own error.
node_reachable=0
if node_error=$(node true 2>&1); then
  node_reachable=1
else
  bad "node: ssh to $NODE failed: $node_error (a node that takes a password needs SSH_CONTROL_PATH, a master connection opened by hand)"
fi

check_plan
if [ -r "$work/plan.json" ] && [ "$node_reachable" -eq 1 ]; then
  check_image
elif [ -r "$work/plan.json" ]; then
  bad "image: the node is not reachable"
else
  bad "image: no plan to read the image volume from"
fi
if [ "$node_reachable" -eq 1 ]; then
  check_vm
  if [ "$stage" = before ]; then
    check_snapshots
  fi
  check_dump
  check_grant
fi
if [ "$stage" = before ]; then
  check_dns
fi

echo
if [ "$failed" -gt 0 ]; then
  echo "$failed check(s) failed"
  exit 1
fi
echo "all checks passed"
