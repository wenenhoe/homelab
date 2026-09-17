#!/bin/sh
# Save an OpenBao raft snapshot, encrypt it, and push it to R2 and B2 -
# one process on `controller`, over the network, using the native
# `bao` CLI (Stage 4 of docs/projects/openbao-cli-standardization.md).
# Replaces ansible/roles/openbao_backup's rendered snapshot-push.sh:
# `bao operator raft snapshot save` is a plain client-side download
# (confirmed live - see
# docs/decisions/drafts/openbao-native-cli-not-docker-based-access.md's
# Context), so the old docker-exec/docker-cp/`security`-local/manual
# mint-on-controller-paste-on-security handoff is gone. rclone still
# runs as a throwaway container (`rclone/rclone:1.75`, same pin as
# every other rclone caller in this repo), not a native binary -
# nothing else here needed that dependency added.
#
# Login mirrors docker/openbao/scripts/bao-login.sh's shape (role_id
# argument, secret_id via hidden prompt, never a file or subprocess
# argument) but calls the native `bao` binary directly instead of
# `docker exec`, and fetches step-ca's root cert fresh over SSH the
# same way bao-login-from-controller.sh did (ADR 0022's mechanism).
# Everything this run creates - root cert, secret_id, rclone.conf, the
# snapshot itself - lives under one `mktemp -d` scratch dir, removed in
# the same trap that revokes the token; nothing is left behind on
# `controller` afterward, unlike the old script's persistent staging
# directory.
#
# Usage, from the repo root on `controller`:
#   tools/openbao_utils/scripts/snapshot-push.sh <role_id>

set -eu

role_id="${1:?usage: snapshot-push.sh <role_id>}"
repo_root=$(cd "$(dirname "$0")/../../.." && pwd)

ssh_info=$(cd "$repo_root/tools" && python3 -c "
from utils.repo import security_ssh_target, main_domain
user, host, key_path = security_ssh_target()
print(user)
print(host)
print(key_path)
print(main_domain())
")
ssh_user=$(printf '%s' "$ssh_info" | sed -n '1p')
ssh_host=$(printf '%s' "$ssh_info" | sed -n '2p')
ssh_key=$(printf '%s' "$ssh_info" | sed -n '3p')
main_domain=$(printf '%s' "$ssh_info" | sed -n '4p')

work_dir=$(mktemp -d)
chmod 700 "$work_dir"
token=""

cleanup() {
  stty echo 2>/dev/null || true
  if [ -n "$token" ]; then
    bao token revoke -self >/dev/null 2>&1 || true
  fi
  rm -rf "$work_dir"
}
trap cleanup EXIT INT TERM

echo "Fetching step-ca's root cert..."
ssh -i "$ssh_key" -o StrictHostKeyChecking=accept-new "$ssh_user@$ssh_host" \
  docker exec step-ca cat /home/step/certs/root_ca.crt > "$work_dir/root_ca.crt"
chmod 600 "$work_dir/root_ca.crt"

export BAO_ADDR="https://openbao.sec.lan.$main_domain:8200"
export BAO_CACERT="$work_dir/root_ca.crt"
export BAO_TLS_SERVER_NAME="openbao.sec.lan.$main_domain"

stty -echo 2>/dev/null || true
printf 'secret_id: ' >&2
read -r secret_id
stty echo 2>/dev/null || true
printf '\n' >&2
printf '%s' "$secret_id" > "$work_dir/secret_id"
chmod 600 "$work_dir/secret_id"

token=$(bao write -field=token auth/approle/login role_id="$role_id" secret_id=@"$work_dir/secret_id")
rm -f "$work_dir/secret_id"
export BAO_TOKEN="$token"

kv_value() {
  bao kv get -mount=secret -field=value "cloud_credentials/leaf/$1"
}

STAGING="${work_dir}/staging"
mkdir -p "$STAGING"
chmod 700 "$STAGING"

TS=$(date -u +%Y%m%dT%H%M%SZ)
RAW="${STAGING}/snapshot-${TS}.snap"
ENC="${STAGING}/snapshot-${TS}.snap.gpg"
GPG_PUBKEY="${repo_root}/ansible/files/backup-gpg-public-key.asc"
RCLONE_CONF="${work_dir}/rclone.conf"

echo "Saving raft snapshot from openbao..."
bao operator raft snapshot save "$RAW"

echo "Encrypting (independently of Vault's own encryption)..."
gpg --batch --yes --trust-model always \
  --output "$ENC" \
  --encrypt --recipient-file "$GPG_PUBKEY" \
  "$RAW"
rm -f "$RAW"

echo "Building rclone.conf..."
r2_account_id=$(kv_value cloudflare-r2-account-id)
b2_region=$(kv_value backblaze-b2-region)

: > "$RCLONE_CONF"
chmod 600 "$RCLONE_CONF"
cat >> "$RCLONE_CONF" <<EOF
[r2]
type = s3
provider = Other
access_key_id = $(kv_value cloudflare-r2-openbao-snapshot-write-access-key)
secret_access_key = $(kv_value cloudflare-r2-openbao-snapshot-write-secret-key)
endpoint = https://${r2_account_id}.r2.cloudflarestorage.com
force_path_style = true
# Required, not optional - see docs/cloud-credential-creation.md's
# "rclone config requirements verification depends on".
no_check_bucket = true
region = auto

[b2]
type = s3
provider = Other
access_key_id = $(kv_value backblaze-b2-openbao-snapshot-write-access-key)
secret_access_key = $(kv_value backblaze-b2-openbao-snapshot-write-secret-key)
endpoint = https://s3.${b2_region}.backblazeb2.com
force_path_style = true
no_check_bucket = true
region = ${b2_region}
EOF

for remote in r2 b2; do
  echo "Pushing to ${remote}:openbao-snapshots/..."
  docker run --rm \
    -v "${RCLONE_CONF}:/config/rclone/rclone.conf:ro" \
    -v "${STAGING}:/data:ro" \
    rclone/rclone:1.75 \
    copy "/data/$(basename "$ENC")" "${remote}:openbao-snapshots/"
done

echo "Done: $(basename "$ENC") pushed to R2 and B2."
