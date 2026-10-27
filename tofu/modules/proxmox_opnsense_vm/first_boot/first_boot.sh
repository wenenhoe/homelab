#!/usr/bin/env bash
# Start the gateway VM and answer its first boot, from the operator host.
# Usage: first_boot.sh VMID OUTPUT_DIR
# The VM must have been created stopped (started = false) with the seed disk
# attached. The script starts it, runs import_seed.py on the Proxmox node beside
# the VM's serial socket with the seed's root password on stdin, and brings the
# console transcript, the result and the GUI certificate back to OUTPUT_DIR.
# Environment: NODE (ssh target, e.g. root@pve), CREDENTIALS (default
# ~/.config/tofu/credentials.tfvars), SEED_DISK (default da1), SSH_CONTROL_PATH
# (socket of an ssh master connection opened by hand, for a node that takes a
# password: ssh -fN -M -S /tmp/opn-ssh.sock root@pve).
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
vmid=${1:?usage: first_boot.sh VMID OUTPUT_DIR}
out=${2:?usage: first_boot.sh VMID OUTPUT_DIR}
: "${NODE:?set NODE to the ssh target of the Proxmox node}"
credentials=${CREDENTIALS:-$HOME/.config/tofu/credentials.tfvars}
seed_disk=${SEED_DISK:-da1}
umask 077

ssh_opts=(-o BatchMode=yes -o ServerAliveInterval=15 -o ConnectTimeout=15)
[ -z "${SSH_CONTROL_PATH:-}" ] || ssh_opts+=(-o "ControlPath=$SSH_CONTROL_PATH")
# The remote command is built here on purpose: the VMID and paths are expanded on this side.
# shellcheck disable=SC2029
node() { ssh "${ssh_opts[@]}" "$NODE" "$@"; }

password=$(sed -n 's/^[[:space:]]*opnsense_root_password[[:space:]]*=[[:space:]]*"\([^"]*\)".*$/\1/p' "$credentials")
if [ -z "$password" ]; then
  echo "$credentials holds no opnsense_root_password; build the seed first" >&2
  exit 1
fi

# The importer is offered only at the first boot, so a VM that has run is past it.
status=$(node "qm status $vmid")
if [ "$status" != "status: stopped" ]; then
  echo "VM $vmid is not stopped ($status); the importer is offered only at its first boot" >&2
  exit 1
fi

mkdir -p "$out"
scratch=$(node "mktemp -d /tmp/opn-first-boot.XXXXXX")
trap 'node "rm -rf $scratch"' EXIT
scp -q "${ssh_opts[@]}" "$here/import_seed.py" "$NODE:$scratch/"

node "qm start $vmid"
rc=0
printf '%s\n' "$password" | node "python3 -I $scratch/import_seed.py --socket /var/run/qemu-server/$vmid.serial0 --seed-disk $seed_disk --log $scratch/console.log --result $scratch/result.json --cert-out $scratch/gateway-cert.pem" || rc=$?

for file in console.log result.json gateway-cert.pem; do
  node "cat $scratch/$file" > "$out/$file" 2> /dev/null || rm -f "$out/$file"
done

# The transcript and result are what gets sent when a boot goes wrong, so they must not hold the password.
if grep -rqF -- "$password" "$out"; then
  rm -f "$out/console.log" "$out/result.json" "$out/gateway-cert.pem"
  echo "the root password was found in the output, which was removed" >&2
  exit 1
fi

if [ "$rc" != 0 ]; then
  echo "the importer driver exited $rc; VM $vmid is left as it is. A first boot that did not take the seed cannot be repeated: destroy the VM and apply the module again" >&2
  exit "$rc"
fi
echo "gateway certificate: $out/gateway-cert.pem"
