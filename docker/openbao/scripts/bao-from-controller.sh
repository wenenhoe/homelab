#!/bin/sh
# Run an arbitrary `bao` command against OpenBao's real network
# address, from `controller` - not `docker exec` into the container.
# Companion to bao-login-from-controller.sh (that one gets a token;
# this one spends it). Same TLS trust mechanism: step-ca's root cert,
# fetched fresh over SSH each run, never skip-verify.
#
# Uses BAO_ADDR/BAO_CACERT env vars rather than -address/-ca-cert
# flags, so arbitrary subcommands (`kv put -mount=... path key=val`)
# can be passed through unmodified - no need to know where in a given
# command's own flag/positional-arg order extra flags would have to
# be inserted.
#
# Requires BAO_TOKEN already exported (see
# bao-login-from-controller.sh). Passed through via -e, never written
# to a file or given as an argument.
#
# Usage, from the repo root on `controller`, after exporting BAO_TOKEN:
#   docker/openbao/scripts/bao-from-controller.sh kv put -mount=secret hosts/_stage3-test probe=stage3
#   docker/openbao/scripts/bao-from-controller.sh kv get -mount=secret hosts/_stage3-test
#   docker/openbao/scripts/bao-from-controller.sh kv metadata delete -mount=secret hosts/_stage3-test

set -eu

: "${BAO_TOKEN:?BAO_TOKEN must already be exported - see bao-login-from-controller.sh}"

repo_root=$(cd "$(dirname "$0")/../../.." && pwd)

ssh_info=$(cd "$repo_root/ansible" && python3 -c "
from cloud_credentials.cache import _security_ssh_target, _main_domain
user, host, key_path = _security_ssh_target()
print(user)
print(host)
print(key_path)
print(_main_domain())
")
ssh_user=$(printf '%s' "$ssh_info" | sed -n '1p')
ssh_host=$(printf '%s' "$ssh_info" | sed -n '2p')
ssh_key=$(printf '%s' "$ssh_info" | sed -n '3p')
main_domain=$(printf '%s' "$ssh_info" | sed -n '4p')

work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT INT TERM

ssh -i "$ssh_key" -o StrictHostKeyChecking=accept-new "$ssh_user@$ssh_host" \
  docker exec step-ca cat /home/step/certs/root_ca.crt > "$work_dir/root_ca.crt"
chmod 600 "$work_dir/root_ca.crt"

docker run --rm \
  --entrypoint bao \
  --user "$(id -u):$(id -g)" \
  -e BAO_TOKEN \
  -e BAO_ADDR="https://openbao.sec.lan.$main_domain:8200" \
  -e BAO_CACERT=/tmp/root_ca.crt \
  -v "$work_dir/root_ca.crt:/tmp/root_ca.crt:ro" \
  openbao/openbao:2.6.2 \
  "$@"
