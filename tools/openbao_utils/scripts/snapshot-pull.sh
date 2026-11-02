#!/bin/sh
# Fetch the newest OpenBao raft snapshot from R2 (then B2) and decrypt it, for
# the restore drill's steps 2 and 3 (docs/topics/secrets/openbao-backup-restore.md).
# snapshot-push.sh is its counterpart. Nothing here reads OpenBao or the file
# cache: the credential is the break-glass read-only one that
# tools/cloud_credentials/create_snapshot_readonly_keys.py prints once, and the
# store it would live in is what is being restored.
#
# Nothing secret is an argument or in the environment. The credential's secret
# half is read from the terminal with echo off and reaches rclone in a 0600
# rclone.conf. The backup key's passphrase is asked for by gpg itself (pinentry),
# against a throwaway keyring built from the exported private key, so the key
# never joins the operator's own keyring.
#
# Everything this run creates - rclone.conf, the encrypted snapshot, the
# keyring - lives under one `mktemp -d` scratch dir, removed in the same trap
# that turns terminal echo back on. Only the decrypted snapshot is left, at
# OUTPUT, mode 0600. It is the contents of OpenBao: delete it once the restore
# is done.
#
# Usage:
#   tools/openbao_utils/scripts/snapshot-pull.sh [r2|b2] [OUTPUT]
# With no provider it tries R2, then B2. OUTPUT defaults to ./restore.snap and
# is never overwritten.

set -eu

provider="${1:-}"
output="${2:-restore.snap}"
case "$provider" in
  "" | r2 | b2) ;;
  *)
    echo "usage: snapshot-pull.sh [r2|b2] [OUTPUT]" >&2
    exit 2
    ;;
esac

if [ -e "$output" ]; then
  echo "$output exists; remove it or name another OUTPUT." >&2
  exit 2
fi

work_dir=$(mktemp -d)
chmod 700 "$work_dir"

cleanup() {
  stty echo 2>/dev/null || true
  gpgconf --homedir "$work_dir/gnupg" --kill gpg-agent >/dev/null 2>&1 || true
  rm -rf "$work_dir"
  [ -z "${partial:-}" ] || rm -f "$partial"
}
trap cleanup EXIT INT TERM

ask() {
  printf '%s: ' "$1" >&2
  read -r "$2"
}

ask_hidden() {
  stty -echo 2>/dev/null || true
  printf '%s: ' "$1" >&2
  read -r "$2"
  stty echo 2>/dev/null || true
  printf '\n' >&2
}

# Writes $work_dir/rclone.conf for one provider. printf and the here-document
# are shell built-ins, so no credential is in any process's arguments.
write_conf() {
  remote="$1"
  account_id="" region="" access_key_id="" secret_access_key=""
  : > "$work_dir/rclone.conf"
  chmod 600 "$work_dir/rclone.conf"
  case "$remote" in
    r2)
      ask "R2 account id" account_id
      ask "R2 access key id" access_key_id
      ask_hidden "R2 secret access key" secret_access_key
      cat >> "$work_dir/rclone.conf" <<EOF
[r2]
type = s3
provider = Other
access_key_id = ${access_key_id}
secret_access_key = ${secret_access_key}
endpoint = https://${account_id}.r2.cloudflarestorage.com
force_path_style = true
no_check_bucket = true
region = auto
EOF
      ;;
    b2)
      ask "B2 region" region
      ask "B2 key id" access_key_id
      ask_hidden "B2 application key" secret_access_key
      cat >> "$work_dir/rclone.conf" <<EOF
[b2]
type = s3
provider = Other
access_key_id = ${access_key_id}
secret_access_key = ${secret_access_key}
endpoint = https://s3.${region}.backblazeb2.com
force_path_style = true
no_check_bucket = true
region = ${region}
EOF
      ;;
  esac
  secret_access_key=""
}

run_rclone() {
  docker run --rm --user "$(id -u):$(id -g)" \
    --cap-drop ALL --security-opt no-new-privileges:true \
    -v "$work_dir/rclone.conf:/config/rclone/rclone.conf:ro" \
    -v "$work_dir/in:/data" \
    rclone/rclone:1.75 "$@"
}

mkdir "$work_dir/in"
fetched=""
for remote in r2 b2; do
  [ -z "$provider" ] || [ "$provider" = "$remote" ] || continue
  echo "Reading ${remote}:openbao-snapshots/..." >&2
  write_conf "$remote"
  if ! listing=$(run_rclone lsf "${remote}:openbao-snapshots/"); then
    echo "Listing ${remote} FAILED" >&2
    continue
  fi
  newest=$(printf '%s\n' "$listing" | grep -E '^snapshot-.*\.snap\.gpg$' | sort | tail -n 1 || true)
  if [ -z "$newest" ]; then
    echo "${remote} holds no snapshot" >&2
    continue
  fi
  echo "Fetching ${newest}..." >&2
  if run_rclone copyto "${remote}:openbao-snapshots/${newest}" "/data/${newest}"; then
    fetched="$newest"
    break
  fi
  echo "Fetching from ${remote} FAILED" >&2
done

if [ -z "$fetched" ]; then
  echo "No snapshot fetched." >&2
  exit 1
fi

key_file=""
ask "Path to the exported backup private key (homelab-backup-private.asc)" key_file
mkdir "$work_dir/gnupg"
chmod 700 "$work_dir/gnupg"
# gpg's agent asks for the passphrase on this terminal.
if tty -s 2>/dev/null; then
  GPG_TTY=$(tty)
  export GPG_TTY
fi
gpg --batch --homedir "$work_dir/gnupg" --import "$key_file"

partial="${output}.partial"
(
  umask 077
  gpg --homedir "$work_dir/gnupg" --output "$partial" --decrypt "$work_dir/in/$fetched"
)

# A snapshot is a gzip stream; anything else means the wrong key or file.
if [ "$(head -c 2 "$partial" | od -An -tx1 | tr -d ' \n')" != 1f8b ]; then
  echo "The decrypted file is not a snapshot (no gzip header)." >&2
  exit 1
fi
mv "$partial" "$output"
partial=""

echo "Wrote ${output} from ${fetched} (mode 600). Delete it once the restore is done."
