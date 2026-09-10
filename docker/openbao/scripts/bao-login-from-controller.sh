#!/bin/sh
# Log in to OpenBao at its real network address, from `controller` -
# not `docker exec` into the container (see bao-login.sh for that
# case, used on `security` itself). Verifies TLS properly against
# step-ca's root cert, fetched fresh each run over SSH - the same
# trust mechanism ADR 0022 already established for cloud_credentials'
# own login flow (cache.py's _fetch_root_cert), reused here rather
# than re-derived. Never skip-verify.
#
# role_id isn't sensitive, passed as a normal argument. secret_id is
# read via a hidden prompt, written to a 600-permission temp file,
# bind-mounted read-only into a throwaway container, then deleted
# immediately - never a literal argument to any process. The
# throwaway container runs as the invoking host user (--user), not
# the image's own non-root `openbao` user: a bind mount keeps its
# host-side ownership, so the image's default user can't read a
# 600-mode file it doesn't own. This is a one-shot CLI call, not the
# server, so borrowing the host's identity for it costs nothing.
#
# Run from the repo root on `controller`:
#   BAO_TOKEN=$(docker/openbao/scripts/bao-login-from-controller.sh <role_id>)
#   export BAO_TOKEN

set -eu

role_id="${1:?usage: bao-login-from-controller.sh <role_id>}"
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
cleanup() {
  stty echo 2>/dev/null || true
  rm -rf "$work_dir"
}
trap cleanup EXIT INT TERM

ssh -i "$ssh_key" -o StrictHostKeyChecking=accept-new "$ssh_user@$ssh_host" \
  docker exec step-ca cat /home/step/certs/root_ca.crt > "$work_dir/root_ca.crt"
chmod 600 "$work_dir/root_ca.crt"

stty -echo 2>/dev/null || true
printf 'secret_id: ' >&2
read -r secret_id
stty echo 2>/dev/null || true
printf '\n' >&2
printf '%s' "$secret_id" > "$work_dir/secret_id"
chmod 600 "$work_dir/secret_id"

docker run --rm \
  --entrypoint bao \
  --user "$(id -u):$(id -g)" \
  -v "$work_dir/root_ca.crt:/tmp/root_ca.crt:ro" \
  -v "$work_dir/secret_id:/tmp/secret_id:ro" \
  openbao/openbao:2.6.2 \
  write -address="https://openbao.sec.lan.$main_domain:8200" \
    -ca-cert=/tmp/root_ca.crt \
    -field=token \
    auth/approle/login role_id="$role_id" secret_id=@/tmp/secret_id
