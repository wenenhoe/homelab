#!/usr/bin/env bash
# Builds a scratch OPNsense gateway with scratch_gateway.sh, applies the gateway's play to it and
# checks what the play must leave behind: a second run with --check reports no change, a forward
# the play does not write is reported by --check and removed by a run, the GUI login needs the
# one-time code in front of the password, and the API key may make only the calls the play needs.
# The gateway is removed on every exit path unless KEEP=1.
# Usage: acceptance.sh OUT_DIR IMAGE_URL IMAGE_CHECKSUM
#   OUT_DIR  a directory outside the repository; scratch_gateway.sh keeps its state and
#            credentials.tfvars there, and the results go to OUT_DIR/run-HHMMSS
# Environment: as for scratch_gateway.sh (NODE, PROXMOX_ENDPOINT, PROXMOX_API_TOKEN, VM_ID,
#   SSH_CONTROL_PATH, LOCAL_PORT, ...), plus OPERATOR (an address in the desktops zone for the
#   play's operator host and one reservation, default 192.168.40.250), ANSIBLE_PLAYBOOK (default
#   ansible-playbook), KEEP=1 (leave the gateway up).
# The management name must resolve to 127.0.0.1 on this machine; preflight prints the /etc/hosts line.
set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../.." && pwd)
usage="usage: acceptance.sh OUT_DIR IMAGE_URL IMAGE_CHECKSUM"
mkdir -p "${1:?$usage}"
out=$(cd "$1" && pwd)
url=${2:?$usage}
sum=${3:?$usage}
: "${NODE:?set NODE to the ssh target of the Proxmox node}" "${PROXMOX_ENDPOINT:?}" "${PROXMOX_API_TOKEN:?}"
case "$out/" in "$repo"/*)
  echo "OUT_DIR holds credentials and must be outside the repository: $out" >&2
  exit 1
  ;;
esac
scratch=$repo/tofu/scratch/opnsense/scratch_gateway.sh
defaults=$repo/ansible/roles/opnsense_gateway/defaults/main.yaml
release=$(sed -n 's/^opnsense_gateway_release: "\(.*\)"$/\1/p' "$defaults")
[ -n "$release" ] || {
  echo "no opnsense_gateway_release in $defaults" >&2
  exit 1
}
export WANT_VERSION=${WANT_VERSION:-$release}
vmid=${VM_ID:-501}
local_port=${LOCAL_PORT:-8443}
operator=${OPERATOR:-192.168.40.250}
ansible=${ANSIBLE_PLAYBOOK:-ansible-playbook}
mgmt_name=OPNsense.internal
forward_domains=(host.scratch.lab lan.scratch.lab)
log=$out/run-$(date +%H%M%S)
mkdir -p "$log"
umask 077
fails=0
up=0
ssh_opts=(-o BatchMode=yes -o ConnectTimeout=15)
[ -z "${SSH_CONTROL_PATH:-}" ] || ssh_opts+=(-o "ControlPath=$SSH_CONTROL_PATH")

check() { # check NAME EXIT_STATUS
  if [ "$2" = 0 ]; then echo "CHECK $1: PASS"; else echo "CHECK $1: FAIL"; fails=$((fails + 1)); fi
}
# shellcheck disable=SC2029
node() { ssh "${ssh_opts[@]}" "$NODE" "$@"; }
# The collection's modules reach the gateway through the tunnel, so no proxy may sit in between.
noproxy() { env -u HTTPS_PROXY -u HTTP_PROXY -u ALL_PROXY -u https_proxy -u http_proxy -u all_proxy "$@"; }
play() { # play NAME ARGS...: the repo's play against the scratch gateway
  local name=$1
  shift
  (cd "$repo/ansible" && noproxy ANSIBLE_NOCOLOR=1 "$ansible" playbooks/opnsense.yaml "$@" --diff -e "@$log/extra-vars.json" \
    -e "opnsense_gateway_ca_file=$cert" -e "opnsense_gateway_api_port=$local_port" -e "opnsense_gateway_credentials_file=$creds") > "$log/$name.txt" 2>&1
}
unchanged() { # unchanged NAME: the recap line of a run says nothing changed
  grep -E '^localhost +:' "$log/$1.txt" | grep -qE 'changed=0 '
}
changed() { # changed NAME: the recap line of a run says something changed
  grep -E '^localhost +:' "$log/$1.txt" | grep -qE 'changed=[1-9]'
}
get() { sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\"\\([^\"]*\\)\".*\$/\\1/p" "$creds"; }
cleanup() {
  if [ "$up" = 1 ] && [ "${KEEP:-0}" != 1 ]; then
    "$scratch" down "$out" > "$log/down.txt" 2>&1
    check "the scratch gateway is removed" $?
  elif [ "$up" = 1 ]; then
    echo "KEEP=1: the scratch gateway is still up; remove it with: $scratch down $out"
  fi
}
trap cleanup EXIT

# --- preflight
for t in python3 "$ansible" ansible-galaxy; do
  command -v "$t" > /dev/null || {
    echo "$t is not installed here" >&2
    exit 1
  }
done
if [ "$(getent hosts "$mgmt_name" | awk '{print $1; exit}')" != 127.0.0.1 ]; then
  echo "$mgmt_name must resolve to 127.0.0.1 here. Add this line to /etc/hosts and run again:" >&2
  echo "127.0.0.1 $mgmt_name" >&2
  exit 1
fi
ansible-galaxy collection list oxlorg.opnsense --format json 2> /dev/null | grep -q "\"$release\"" || {
  echo "oxlorg.opnsense $release is not installed: ansible-galaxy collection install -r $repo/ansible/requirements.yml" >&2
  exit 1
}
ansible_python=$(dirname "$(readlink -f "$(command -v "$ansible")")")/python
if [ -x "$ansible_python" ] && ! "$ansible_python" -c 'import httpx' 2> /dev/null; then
  echo "the collection's modules need httpx in ansible's Python: $ansible_python -m pip install httpx" >&2
  exit 1
fi
node true || {
  echo "cannot ssh to $NODE without a prompt: open a master connection and set SSH_CONTROL_PATH" >&2
  exit 1
}
if node "qm status $vmid" > /dev/null 2>&1; then
  echo "VM $vmid exists on the node: a scratch gateway from an earlier run is still there. Remove it first: qm stop $vmid; qm destroy $vmid --purge" >&2
  exit 1
fi

# --- the scratch gateway, from the repo's script
"$scratch" up "$out" "$url" "$sum" 2>&1 | tee "$log/up.txt"
check "the repo's script builds the scratch gateway" "${PIPESTATUS[0]}"
[ -f "$out/scratch.env" ] || {
  echo "nothing recorded as up in $out; see $log/up.txt" >&2
  exit 1
}
up=1
cert=$out/first-boot/gateway-cert.pem
creds=$out/credentials.tfvars
[ -s "$cert" ] || {
  echo "no certificate in $out/first-boot; see $log/up.txt" >&2
  exit 1
}

# --- the play: apply, then check
python3 -I - "$log/extra-vars.json" "$operator" "${forward_domains[@]}" << 'PY'
import json, sys
json.dump({"opnsense_gateway_operator_hosts": [sys.argv[2]],
           "opnsense_gateway_forward_domains": sys.argv[3:],
           "opnsense_gateway_dhcp_reservations": [{"name": "scratch-reservation", "zone": "desktops", "address": sys.argv[2], "mac": "bc:24:11:00:01:91"}]},
          open(sys.argv[1], "w"))
PY
play play-apply
check "the play applies" $?
play play-check --check
check "a second run with --check exits cleanly" $?
unchanged play-check
check "the second run reports no change" $?

# --- a forward the play does not write: --check reports it, a run removes it
(cd "$here" && noproxy ANSIBLE_NOCOLOR=1 "$ansible" stale_forward.yaml -e "ca_file=$cert" -e "api_port=$local_port" \
  -e "credentials=$creds" -e "domain=${forward_domains[0]}" -e "target=192.0.2.99") > "$log/stale-present.txt" 2>&1
check "a forward the play does not write is added behind its back" $?
play play-stale-check --check
changed play-stale-check
check "--check reports the forward the play does not write" $?
play play-stale-apply
check "the play removes the forward it does not write" $?
play play-stale-after --check
unchanged play-stale-after
check "--check is clean again once it is removed" $?

# --- what the gateway lets in
python3 -I "$here/gui_login.py" --credentials "$creds" --ca "$cert" --port "$local_port" | tee "$log/gui-login.txt"
check "the GUI login needs the one-time code in front of the password and refuses everything else" "${PIPESTATUS[0]}"
python3 -I "$here/api_scope.py" --credentials "$creds" --ca "$cert" --port "$local_port" | tee "$log/api-scope.txt"
check "the API key may make the calls the play needs and is refused the others" "${PIPESTATUS[0]}"

# --- nothing in the results may hold a credential value
leaks=$(for v in "$(get opnsense_root_password)" "$(get opnsense_root_otp_seed)" "$(get opnsense_api_key)" "$(get opnsense_api_secret)" "${PROXMOX_API_TOKEN#*=}"; do
  [ "${#v}" -ge 8 ] && grep -rlF -- "$v" "$log" 2> /dev/null
done | sort -u)
if [ -n "$leaks" ]; then
  echo "A CREDENTIAL VALUE IS IN: $leaks"
  fails=$((fails + 1))
else
  echo "CHECK no credential value in the results: PASS"
fi
echo
if [ "$fails" = 0 ]; then echo "ALL CHECKS PASSED"; else echo "$fails CHECK(S) FAILED"; fi
echo "results: $log"
[ "$fails" = 0 ]
