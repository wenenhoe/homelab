#!/bin/sh
# Copy Tofu's state to B2, GPG-encrypted, under a new key each run
# (ADR 0103 - decisions/0103-where-tofus-state-is-held/revision-000.md).
# Run it from anywhere on the host that runs Tofu after each apply.
#
# `tofu state pull` prints the state decrypted, so the plaintext exists only
# in one `mktemp -d` scratch directory, is replaced by its GPG form to the
# backup key straight away, and the directory is removed on every exit.
# The B2 key can write but not delete, so each run uses a new object name
# and `rclone copy` is the only verb. rclone is the throwaway container
# every other caller uses (`rclone/rclone:1.75`).
#
# The two env files come from tools/cloud_credentials/create_state_keys.py.
# The R2 one is sourced for the pull only and the B2 one for the rclone
# config only, so neither provider's credentials reach the other's process.
#
# Usage: tools/tofu_state/state-copy-push.sh

set -eu

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
config_dir="${TOFU_CONFIG_DIR:-$HOME/.config/tofu}"
backend_env="$config_dir/state-backend.env"
copy_env="$config_dir/state-copy.env"

for file in "$backend_env" "$copy_env"; do
  if [ ! -r "$file" ]; then
    echo "Missing $file; run tools/cloud_credentials/create_state_keys.py --provider all" >&2
    exit 1
  fi
done

work_dir=$(mktemp -d)
chmod 700 "$work_dir"
trap 'rm -rf "$work_dir"' EXIT INT TERM

staging="$work_dir/staging"
mkdir -p "$staging"
chmod 700 "$staging"

ts=$(date -u +%Y%m%dT%H%M%SZ)
raw="$work_dir/state.json"
enc="$staging/state-${ts}.json.gpg"
gpg_pubkey="$repo_root/ansible/files/backup-gpg-public-key.asc"
rclone_conf="$work_dir/rclone.conf"

echo "Pulling the state..."
(
  # shellcheck source=/dev/null
  . "$backend_env"
  tofu -chdir="$repo_root/tofu" state pull
) > "$raw"
if [ ! -s "$raw" ]; then
  echo "tofu state pull printed nothing; no copy was made" >&2
  exit 1
fi

echo "Encrypting..."
gpg --batch --yes --trust-model always \
  --output "$enc" \
  --encrypt --recipient-file "$gpg_pubkey" \
  "$raw"
rm -f "$raw"

(
  # shellcheck source=/dev/null
  . "$copy_env"
  umask 077
  cat > "$rclone_conf" <<CONF
[b2]
type = s3
provider = Other
access_key_id = ${STATE_COPY_ACCESS_KEY_ID}
secret_access_key = ${STATE_COPY_SECRET_ACCESS_KEY}
endpoint = ${STATE_COPY_ENDPOINT}
force_path_style = true
no_check_bucket = true
region = ${STATE_COPY_REGION}
CONF
  printf '%s\n' "$STATE_COPY_BUCKET" > "$work_dir/bucket"
)
bucket=$(cat "$work_dir/bucket")

echo "Pushing to b2:${bucket}/state/..."
if ! docker run --rm \
  -v "${rclone_conf}:/config/rclone/rclone.conf:ro" \
  -v "${staging}:/data:ro" \
  rclone/rclone:1.75 \
  copy "/data/$(basename "$enc")" "b2:${bucket}/state/"; then
  echo "Push to b2 FAILED" >&2
  exit 1
fi

echo "Done: $(basename "$enc") pushed to b2:${bucket}/state/."
