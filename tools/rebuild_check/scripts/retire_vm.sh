#!/usr/bin/env bash
# Runs on the Proxmox node, piped in over SSH: bash -s -- ACTION VMID [NAME].
# The node's side of a host rebuild: dump the stopped old VM to the dump storage, destroy it, and
# delete its dump once the rebuilt host is confirmed healthy.
#   dump VMID NAME       vzdump the stopped VM to the dump storage; refuses if a dump of VMID exists
#   destroy VMID NAME    destroy the stopped VM; refuses unless its dump is there and not empty
#   drop-dump VMID       delete VMID's dump, then fstrim the dump volume to hand its blocks back
#   restore VMID NEWVMID restore VMID's dump as a new, stopped VM at NEWVMID (900 or above), the rollback
# NAME is the VM's name in Proxmox. It has to match, so a mistyped VMID cannot dump or destroy another
# VM. The dump is the only rollback for a destroyed VM, so destroy never runs without one that zstd can
# read to the end. A restore keeps the old VM's address, so the copy is left stopped, with a new MAC and
# no start on boot, until its address is sorted. RESTORE_STORAGE names the storage for its disks; unset,
# the disks go back where the dump says they were.
# DUMP_STORAGE and DUMP_DIR name the dump storage and where it is mounted. The archives sit in its dump/
# subdirectory, where Proxmox puts the backups of a directory storage.
set -euo pipefail

storage=${DUMP_STORAGE:-vzdump}
dump_dir=${DUMP_DIR:-/mnt/vzdump}
archive_dir=$dump_dir/dump

usage() {
  echo "usage: bash -s -- dump|destroy VMID NAME | drop-dump VMID | restore VMID NEWVMID" >&2
  exit 2
}

fail() {
  echo "$*" >&2
  exit 1
}

action=${1:-}
vmid=${2:-}
name=${3:-}
case "$action" in
  dump | destroy) [ "$#" -eq 3 ] || usage ;;
  drop-dump) [ "$#" -eq 2 ] || usage ;;
  restore) [ "$#" -eq 3 ] || usage ;;
  *) usage ;;
esac
[[ "$vmid" =~ ^[0-9]+$ ]] || usage
if [ "$action" = restore ]; then
  [[ "$name" =~ ^[0-9]+$ ]] || usage
  [ "$name" -ge 900 ] || fail "the restored VM takes a VMID of 900 or above, not $name: a lower one is a real host's"
fi

# A dump directory that is not mounted is the node's root filesystem, which a dump would fill.
require_dump_storage() {
  mountpoint -q "$dump_dir" || fail "$dump_dir is not a mount point: the dump storage is not mounted"
  pvesm status --storage "$storage" > /dev/null || fail "no storage named $storage"
}

require_stopped_vm_named() {
  local config got
  config=$(qm config "$vmid") || fail "no VM $vmid"
  got=$(awk -F': ' '$1 == "name" {print $2}' <<< "$config")
  [ "$got" = "$name" ] || fail "VM $vmid is named '$got', not '$name'"
  [ "$(qm status "$vmid")" = "status: stopped" ] || fail "VM $vmid is not stopped"
}

# The dump's archive; its log and notes sit beside it under the same prefix.
dump_archives() {
  shopt -s nullglob
  archives=("$archive_dir"/vzdump-qemu-"$vmid"-*.vma.zst)
  shopt -u nullglob
}

require_one_nonempty_dump() {
  dump_archives
  [ "${#archives[@]}" -eq 1 ] || fail "expected one dump of VM $vmid in $archive_dir, found ${#archives[@]}"
  [ -s "${archives[0]}" ] || fail "the dump ${archives[0]} is empty"
}

# A truncated archive passes the size check, so read it through: a rollback that cannot be unpacked is none.
require_readable_dump() {
  zstd -t -q -- "${archives[0]}" || fail "the dump ${archives[0]} does not pass zstd -t: it is not a usable rollback"
}

report_free_space() {
  echo "free on $dump_dir: $(df -h --output=avail "$dump_dir" | tail -n 1 | tr -d ' ')"
}

case "$action" in
  dump)
    require_dump_storage
    require_stopped_vm_named
    dump_archives
    [ "${#archives[@]}" -eq 0 ] || fail "VM $vmid already has a dump in $archive_dir: ${archives[0]}"
    report_free_space
    vzdump "$vmid" --storage "$storage" --compress zstd --mode stop
    require_one_nonempty_dump
    require_readable_dump
    echo "dumped VM $vmid to ${archives[0]} ($(stat -c %s "${archives[0]}") bytes)"
    report_free_space
    ;;
  destroy)
    require_dump_storage
    require_stopped_vm_named
    require_one_nonempty_dump
    require_readable_dump
    qm destroy "$vmid" --purge 1 --destroy-unreferenced-disks 1
    echo "destroyed VM $vmid; its dump is ${archives[0]}"
    ;;
  drop-dump)
    require_dump_storage
    dump_archives
    [ "${#archives[@]}" -gt 0 ] || fail "no dump of VM $vmid in $archive_dir"
    rm -f -- "$archive_dir"/vzdump-qemu-"$vmid"-*
    fstrim -v "$dump_dir"
    report_free_space
    ;;
  restore)
    require_dump_storage
    require_one_nonempty_dump
    require_readable_dump
    if qm config "$name" > /dev/null 2>&1; then fail "VM $name already exists"; fi
    restore_args=("${archives[0]}" "$name" --unique 1)
    [ -z "${RESTORE_STORAGE:-}" ] || restore_args+=(--storage "$RESTORE_STORAGE")
    qmrestore "${restore_args[@]}"
    qm set "$name" --onboot 0 > /dev/null
    echo "restored VM $vmid as VM $name, stopped: it has the old VM's address, so keep it off the network until that is sorted"
    ;;
esac
