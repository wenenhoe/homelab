#!/usr/bin/env bash
# Runs on the Proxmox node, at its console or piped in over SSH: bash -s -- VMID NAME NET BRIDGE TAG.
# Moves one NIC of a VM to another bridge and VLAN tag and keeps the rest of it: the model, the MAC address
# and any other option. It is how the operator host leaves the gateway's bridge for the physical one while
# the gateway is down, and returns.
#   VMID    the VM
#   NAME    its name in Proxmox; has to match, so a mistyped VMID moves no other VM's NIC
#   NET     the NIC, net0 for the first
#   BRIDGE  the bridge to attach it to
#   TAG     the VLAN tag, or none for an untagged NIC
# It prints the NIC's line before and after, so the way back is on the screen. The change applies to a
# running VM at once and drops any connection the NIC carries, SSH included, so run it where that
# does not matter: the node's console, or a session the move does not depend on.
set -euo pipefail

usage="usage: bash -s -- VMID NAME NET BRIDGE TAG|none"
fail() {
  echo "$*" >&2
  exit 1
}

[ "$#" -eq 5 ] || {
  echo "$usage" >&2
  exit 2
}
vmid=$1
name=$2
net=$3
bridge=$4
tag=$5
[[ "$vmid" =~ ^[0-9]+$ ]] || {
  echo "$usage" >&2
  exit 2
}
[[ "$net" =~ ^net[0-9]+$ ]] || {
  echo "$usage" >&2
  exit 2
}
[[ "$bridge" =~ ^[A-Za-z0-9_.-]+$ ]] || {
  echo "$usage" >&2
  exit 2
}
[[ "$tag" =~ ^([0-9]+|none)$ ]] || {
  echo "$usage" >&2
  exit 2
}

config=$(qm config "$vmid") || fail "no VM $vmid"
got=$(awk -F': ' '$1 == "name" {print $2; exit}' <<< "$config")
[ "$got" = "$name" ] || fail "VM $vmid is named '$got', not '$name'"
old=$(awk -v net="$net" -F': ' '$1 == net {print $2; exit}' <<< "$config")
[ -n "$old" ] || fail "VM $vmid has no $net"

IFS=, read -ra parts <<< "$old"
saw_bridge=0
new_parts=()
for part in "${parts[@]}"; do
  case "$part" in
    bridge=*)
      saw_bridge=1
      new_parts+=("bridge=$bridge")
      ;;
    tag=*) ;;
    *) new_parts+=("$part") ;;
  esac
done
[ "$saw_bridge" -eq 1 ] || fail "$net of VM $vmid names no bridge: $old"
[ "$tag" = none ] || new_parts+=("tag=$tag")
new=$(
  IFS=,
  echo "${new_parts[*]}"
)

echo "$net of VM $vmid was: $old"
qm set "$vmid" "--$net" "$new" > /dev/null
echo "$net of VM $vmid is now: $new"
