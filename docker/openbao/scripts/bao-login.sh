#!/bin/sh
# Log in to OpenBao via AppRole without secret_id ever appearing in
# shell history or `ps` output.
#
# role_id isn't sensitive (openbao-auth.md already treats it this
# way), so it's a normal argument. secret_id is read via a hidden
# prompt, piped into a temp file INSIDE the openbao container (never
# a literal argument to any process), referenced via bao's @file
# syntax, then deleted immediately.
#
# Confirmed against a live 2.6.2 instance: `@-` is NOT stdin shorthand
# for this bao build - "error reading file: open -: no such file or
# directory". @ only accepts a real path, hence the temp-file dance
# below instead of a single piped @- read.
#
# Usage, on `security` (wherever `docker exec` reaches the `openbao`
# container):
#   BAO_TOKEN=$(docker/openbao/scripts/bao-login.sh <role_id>)
#   export BAO_TOKEN

set -eu

role_id="${1:?usage: bao-login.sh <role_id>}"
tmp_path="/tmp/.bao-login-secret-$$"

cleanup() {
  stty echo 2>/dev/null || true
  docker exec openbao rm -f "$tmp_path" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

stty -echo 2>/dev/null || true
printf 'secret_id: ' >&2
read -r secret_id
printf '\n' >&2

printf '%s' "$secret_id" | docker exec -i openbao sh -c "umask 077; cat > $tmp_path"

docker exec -e BAO_SKIP_VERIFY=true openbao \
  bao write -field=token auth/approle/login \
  role_id="$role_id" secret_id="@$tmp_path"
