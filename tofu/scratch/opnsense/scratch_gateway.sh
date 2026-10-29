#!/usr/bin/env bash
# Build and tear down a scratch OPNsense gateway for developing the gateway's play.
# Usage: scratch_gateway.sh up OUT_DIR IMAGE_URL IMAGE_CHECKSUM
#        scratch_gateway.sh down OUT_DIR
# up builds the seed (credentials go to OUT_DIR/credentials.tfvars, never the real file),
# applies the OPNsense module with the VM stopped, answers the importer at its first boot,
# updates the gateway to WANT_VERSION and opens a tunnel from this machine's LOCAL_PORT to
# the gateway's GUI port through the node. It prints the play command to run. down closes
# the tunnel and destroys the VM and everything up left on the node.
# IMAGE_URL and IMAGE_CHECKSUM are the nano image of the pinned release and its published
# SHA-256, from the release mirror.
# Environment: NODE (ssh target, e.g. root@pve), PROXMOX_ENDPOINT, PROXMOX_API_TOKEN
#   (user@realm!id=secret); optional PROXMOX_INSECURE=true, NODE_NAME (default pve),
#   VM_ID (default 501), LAN_BRIDGE (an isolated bridge with no ports, default vmbr9),
#   WAN_BRIDGE (default vmbr1), WAN_VLAN_ID (tag of the WAN NIC when the route out is on a
#   VLAN), TOFU (default tofu), SSH_CONTROL_PATH (socket of an ssh master connection opened
#   by hand, for a node that takes a password), WANT_VERSION (default 26.1.11),
#   ALLOW_LATEST=1, LOCAL_PORT (default 8443), MIN_FREE_KB (free space required where OUT_DIR is,
#   default 8000000).
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../.." && pwd)
mod=$repo/tofu/modules/proxmox_opnsense_vm
usage="usage: scratch_gateway.sh up OUT_DIR IMAGE_URL IMAGE_CHECKSUM | down OUT_DIR"
action=${1:?$usage}
mkdir -p "${2:?$usage}"
out=$(cd "$2" && pwd)
: "${NODE:?set NODE to the ssh target of the Proxmox node}"
vmid=${VM_ID:-501}
lan_bridge=${LAN_BRIDGE:-vmbr9}
wan_bridge=${WAN_BRIDGE:-vmbr1}
want_version=${WANT_VERSION:-26.1.11}
local_port=${LOCAL_PORT:-8443}
tofu=${TOFU:-tofu}
# The seed gives the gateway this LAN address, and the node takes another on the same bridge.
lan_ip=192.168.77.1
node_ip=192.168.77.10
state=$out/scratch.env
creds=$out/credentials.tfvars
umask 077

ssh_opts=(-o BatchMode=yes -o ServerAliveInterval=15 -o ConnectTimeout=15)
[ -z "${SSH_CONTROL_PATH:-}" ] || ssh_opts+=(-o "ControlPath=$SSH_CONTROL_PATH")
# The remote command is built here on purpose: the VMID, bridge and paths are expanded on this side.
# shellcheck disable=SC2029
node() { ssh "${ssh_opts[@]}" "$NODE" "$@"; }
die() {
  echo "$*" >&2
  exit 1
}
tf() { (cd "$here" && TF_IN_AUTOMATION=1 TF_DATA_DIR="$out/.terraform" "$tofu" "$@"); }

export TF_VAR_proxmox_endpoint=${PROXMOX_ENDPOINT:-}
export TF_VAR_proxmox_api_token=${PROXMOX_API_TOKEN:-}
export TF_VAR_proxmox_insecure=${PROXMOX_INSECURE:-false}
export TF_VAR_node_name=${NODE_NAME:-pve}
export TF_VAR_vm_id=$vmid
export TF_VAR_image_url=${3:-}
export TF_VAR_image_checksum=${4:-}
export TF_VAR_image_cache_dir=$out/image-cache
export TF_VAR_seed_image_path=$out/seed/seed.img
export TF_VAR_lan_bridge=$lan_bridge
export TF_VAR_wan_bridge=$wan_bridge
[ -z "${WAN_VLAN_ID:-}" ] || export TF_VAR_wan_vlan_id=$WAN_VLAN_ID
# The provider writes an upload to a temporary file first, and /tmp is often a small tmpfs.
export TMPDIR=$out/tmp
store=${TF_VAR_image_datastore_id:-tofu-images}

preflight() {
  [ -n "$TF_VAR_image_url" ] && [ -n "$TF_VAR_image_checksum" ] || die "up needs IMAGE_URL and IMAGE_CHECKSUM"
  : "${PROXMOX_ENDPOINT:?}" "${PROXMOX_API_TOKEN:?}"
  local t
  for t in curl bunzip2 openssl xmllint sfdisk mformat python3 "$tofu"; do
    command -v "$t" > /dev/null || die "$t is not installed here"
  done
  [ ! -e "$state" ] || die "$state exists: a scratch gateway from an earlier run is still up. Run down first"
  [ ! -e "$creds" ] || die "$creds exists; use an empty OUT_DIR so the scratch gateway gets fresh credentials"
  node true || die "cannot ssh to $NODE without a prompt: open a master connection and set SSH_CONTROL_PATH"
  node "command -v python3 curl openssl > /dev/null" || die "the node lacks python3, curl or openssl"
  node "test -d /sys/class/net/$lan_bridge" || die "$lan_bridge does not exist on the node: create it as an empty Linux bridge with no ports and no address, and let the API token use it (SDN.Use on /sdn/zones/localnetwork/$lan_bridge)"
  # The seed's LAN serves DHCP, so it must never share a bridge with anything real.
  [ -z "$(node "ls /sys/class/net/$lan_bridge/brif 2> /dev/null")" ] || die "$lan_bridge has ports attached; use an isolated bridge"
  [ "$wan_bridge" != "$lan_bridge" ] || die "WAN_BRIDGE must differ from the isolated LAN bridge $lan_bridge"
  [ "$wan_bridge" != vmbr0 ] || die "WAN_BRIDGE=vmbr0 is the production WAN bridge; a scratch gateway must not be given it"
  node "test -d /sys/class/net/$wan_bridge" || die "$wan_bridge does not exist on the node"
  if node "qm status $vmid" > /dev/null 2>&1; then die "VM $vmid exists; destroy it first"; fi
  local leftover
  leftover=$(node "pvesm list $store --content import 2> /dev/null" | grep -E 'opn-scratch-seed\.raw|nano-amd64\.raw' || true)
  [ -z "$leftover" ] || die "files from an earlier run are still stored; remove them first (pvesm free <volid>): $leftover"
  # Download, unpacked image and the provider's temporary copy of the upload: about 7 GB here.
  local free_kb
  free_kb=$(df -Pk "$out" | awk 'NR==2 {print $4}')
  [ "$free_kb" -ge "${MIN_FREE_KB:-8000000}" ] || die "less than 8 GB free where $out is; the image needs about 7 GB"
}

credential() { sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\"\\([^\"]*\\)\".*\$/\\1/p" "$creds"; }

update_gateway() {
  local rd=$1 envf="$out/.gateway.env" reach=1 _
  printf 'API_KEY=%q\nAPI_SECRET=%q\nLAN_IP=%s\n' "$(credential opnsense_api_key)" "$(credential opnsense_api_secret)" "$lan_ip" > "$envf"
  for _ in $(seq "${GATE_TRIES:-45}"); do
    if node "timeout 2 bash -c 'exec 3<>/dev/tcp/$lan_ip/443'" 2> /dev/null; then
      reach=0
      break
    fi
    sleep "${GATE_WAIT:-2}"
  done
  [ "$reach" = 0 ] || die "the gateway does not answer on TCP 443 from the node. Is the node's host firewall dropping $lan_bridge traffic?"
  scp -q "${ssh_opts[@]}" "$here/update_gateway.sh" "$envf" "$out/first-boot/gateway-cert.pem" "$NODE:$rd/"
  rm -f "$envf"
  node "mv $rd/.gateway.env $rd/gateway.env; chmod 600 $rd/gateway.env"
  node "SERIAL_SOCKET=/var/run/qemu-server/$vmid.serial0 ALLOW_LATEST=${ALLOW_LATEST:-0} bash $rd/update_gateway.sh $rd/gateway.env $rd/gateway-cert.pem $want_version $rd/update" | tee "$out/update.txt"
  if grep -q ': FAIL$' "$out/update.txt"; then die "the update reported failed checks; see $out/update.txt"; fi
}

open_tunnel() {
  if [ -z "${SSH_CONTROL_PATH:-}" ]; then
    ssh "${ssh_opts[@]}" -fN -M -S "$out/tunnel.sock" "$NODE" || die "cannot open an ssh connection to $NODE for the tunnel"
    ssh_opts+=(-o "ControlPath=$out/tunnel.sock")
    echo "own_master=1" >> "$state"
  fi
  ssh "${ssh_opts[@]}" -O forward -L "127.0.0.1:$local_port:$lan_ip:443" "$NODE"
  echo "tunnel=1" >> "$state"
}

up() {
  preflight
  mkdir -p "$out/tmp"
  "$mod/seed/build_seed.sh" "$out/seed" --lan-ip "$lan_ip" --credentials "$creds" --wan-dhcp-hostname opn-scratch > "$out/build-seed.txt"
  local rd attempt
  rd=$(node "mktemp -d /tmp/opn-scratch.XXXXXX")
  printf 'vmid=%q\nlan_bridge=%q\nnode_dir=%q\nlocal_port=%q\n' "$vmid" "$lan_bridge" "$rd" "$local_port" > "$state"

  tf init -backend=false -input=false -lockfile=readonly > "$out/init.txt"
  # A 3 GB upload to the node has failed now and then with a closed connection and succeeded on the
  # next try, and resources already created are kept, so a failed apply is retried.
  for attempt in 1 2 3; do
    if tf apply -auto-approve -input=false -state="$out/terraform.tfstate" > "$out/apply.txt" 2>&1; then break; fi
    if [ "$attempt" = 3 ]; then
      tail -30 "$out/apply.txt" >&2
      die "tofu apply failed three times; run down to remove what it made"
    fi
    echo "apply attempt $attempt failed, retrying" >&2
  done

  node "ip addr show dev $lan_bridge | grep -q $node_ip || ip addr add $node_ip/24 dev $lan_bridge"
  CREDENTIALS=$creds "$mod/first_boot/first_boot.sh" "$vmid" "$out/first-boot"
  update_gateway "$rd"
  open_tunnel
  cat << MSG

The scratch gateway is up. Its management name is OPNsense.internal, which must resolve to
127.0.0.1 here (add "127.0.0.1 OPNsense.internal" to /etc/hosts). Run the play with no proxy
variables set:

  cd $repo/ansible && ansible-playbook playbooks/opnsense.yaml --check --diff \\
    -e opnsense_gateway_ca_file=$out/first-boot/gateway-cert.pem \\
    -e opnsense_gateway_api_port=$local_port \\
    -e opnsense_gateway_credentials_file=$creds

Remove it with: $0 down $out
MSG
}

down() {
  [ -f "$state" ] || die "$state does not exist: nothing is recorded as up in $out"
  local vmid lan_bridge node_dir local_port own_master="" tunnel=""
  # shellcheck disable=SC1090
  . "$state"
  if [ -n "$tunnel" ]; then ssh "${ssh_opts[@]}" -O cancel -L "127.0.0.1:$local_port:$lan_ip:443" "$NODE" > /dev/null 2>&1 || true; fi
  if [ -n "$own_master" ]; then ssh -S "$out/tunnel.sock" -O exit "$NODE" > /dev/null 2>&1 || true; fi
  node "qm stop $vmid" > /dev/null 2>&1 || true
  if ! tf destroy -auto-approve -input=false -state="$out/terraform.tfstate" > "$out/destroy.txt" 2>&1; then
    tail -20 "$out/destroy.txt" >&2
    die "tofu destroy failed; the VM and its files may remain"
  fi
  if node "qm status $vmid" > /dev/null 2>&1; then die "VM $vmid is still there after destroy"; fi
  node "ip addr del $node_ip/24 dev $lan_bridge 2> /dev/null; rm -rf $node_dir" || true
  rm -rf "$out/image-cache" "$out/tmp" "$state"
  echo "scratch gateway $vmid removed"
}

case "$action" in
  up) up ;;
  down) down ;;
  *) die "$usage" ;;
esac
