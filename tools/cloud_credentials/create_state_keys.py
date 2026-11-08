#!/usr/bin/env python3
"""Mint the credentials for Tofu's remote state (ADR 0103): the R2 key the
`s3` backend reads, writes, locks and deletes with, and the B2 key that can
only add the encrypted copy pushed after each apply.

Unlike create_snapshot_write_keys.py, neither key is cached to OpenBao. Tofu
has to be able to rebuild the host that runs OpenBao, so its state credentials
sit with its other credentials in files on the host that runs Tofu (ADR 0048),
mode 0600 in a 0700 directory, and this script runs there:

- ~/.config/tofu/state-backend.env: the R2 key, the backend's endpoint, and
  the state encryption passphrase with the Tofu encryption configs built from
  it. Source it before running tofu.
- ~/.config/tofu/state-copy.env: the B2 key and where the copy goes. Write-only,
  no `deleteFiles`, the same shape as the snapshot write leaf.

Both keys carry the quarterly native expiry every other leaf gets, are verified
over rclone before a file is written, and rotate with --rotate (mint, verify,
swap the file, then revoke the old key). The passphrase is made once, printed
once so its offline copy can be taken, and never changes on a rotation: it is
the key to every state object already written.

Usage (run from tools/, on the host that runs Tofu):
    python3 -m cloud_credentials.create_state_keys [--provider {r2,b2,all}]
    python3 -m cloud_credentials.create_state_keys --provider {r2,b2} --rotate
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import shlex
import sys
from pathlib import Path

import requests
from b2sdk.v2.exception import B2Error

from cloud_credentials.expiry import QUARTERLY_SECONDS, utcnow_iso
from cloud_credentials.leaf_keys.b2 import B2_LEAF_CAPABILITIES, b2_delete_key, b2_lookup_bucket_id, b2_rotation_api
from cloud_credentials.leaf_keys.r2 import r2_create_leaf_token, r2_delete_token, r2_permission_group_ids, r2_rotation_token
from cloud_credentials.secret_store import scoped
from cloud_credentials.verify import verify_leaf_via_rclone

# Only reads: both secrets below are written by create_leaf_keys.py and bootstrap.
_, _, _, require_secret = scoped("leaf")

STATE_BUCKET_R2 = "opentofu-state"
STATE_BUCKET_B2 = "opentofu-state-b2"
TOKEN_NAME_R2 = "opentofu-state"  # noqa: S105 - display label for token, not token value
KEY_NAME_B2 = "opentofu-state-copy"

BACKEND_ENV = "state-backend.env"
COPY_ENV = "state-copy.env"


def config_dir() -> Path:
    return Path.home() / ".config" / "tofu"


def encryption_config(passphrase: str, *, migrating: bool = False) -> str:
    """The HCL OpenTofu reads from TF_ENCRYPTION.

    The steady-state config is `enforced`, so a missing or wrong key fails the
    run and never writes plaintext state. The migrating one adds an
    `unencrypted` fallback so `tofu init -migrate-state` can read the local
    plaintext file once; it is used for that one command and no other.
    """
    fallback = (
        """
  fallback {
    method = method.unencrypted.migrate
  }"""
        if migrating
        else ""
    )
    migrate_method = '\nmethod "unencrypted" "migrate" {}' if migrating else ""
    enforced = "" if migrating else "\n  enforced = true"
    return f"""key_provider "pbkdf2" "main" {{
  passphrase = "{passphrase}"
}}
method "aes_gcm" "main" {{
  keys = key_provider.pbkdf2.main
}}{migrate_method}
state {{
  method = method.aes_gcm.main{enforced}{fallback}
}}
plan {{
  method = method.aes_gcm.main{enforced}
}}
"""


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = {}
    for word in shlex.split(path.read_text(), comments=True):
        if word == "export":
            continue
        key, _, value = word.partition("=")
        values[key] = value
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    """Replace `path` atomically with `export KEY=value` lines, mode 0600.

    The temp file is created 0600 in the same directory, so a secret is never
    readable by anyone else, and a crash leaves the old file whole.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    body = "".join(f"export {key}={shlex.quote(value)}\n" for key, value in values.items())
    temp = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def _r2_session_and_groups() -> tuple[requests.Session, str, dict]:
    token = r2_rotation_token()
    account_id = require_secret(
        "cloudflare-r2-account-id",
        "Already required for cloud-sync.md's endpoint — same file, no new step.",
    )
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    return session, account_id, r2_permission_group_ids(session, account_id)


def _b2_region() -> str:
    return require_secret("backblaze-b2-region", "Set via bootstrap.py / secret_catalog.yaml — same value cloud-sync.md's rclone.conf uses.")


def mint_r2(*, rotate: bool = False) -> bool:
    path = config_dir() / BACKEND_ENV
    existing = read_env_file(path)
    if existing and not rotate:
        print(f"r2 {TOKEN_NAME_R2}: {path} already exists, skipping (use --rotate to replace the key)")
        return True
    if rotate and not existing:
        print(f"r2 {TOKEN_NAME_R2}: nothing to rotate, {path} does not exist", file=sys.stderr)
        return False

    session, account_id, group_by_name = _r2_session_and_groups()
    # Item Write is also what lets the backend delete: on R2 the group carries read, write and
    # delete together, which is what Tofu needs for the state and its lock file.
    result = r2_create_leaf_token(session, account_id, group_by_name, "write", bucket=STATE_BUCKET_R2, token_name=TOKEN_NAME_R2)
    access_key, secret_key = result["id"], hashlib.sha256(result["value"].encode()).hexdigest()
    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"

    ok, detail = verify_leaf_via_rclone(access_key, secret_key, endpoint, "auto", STATE_BUCKET_R2, "write")
    if not ok:
        old = f"Old token {existing['AWS_ACCESS_KEY_ID']} left untouched and still in use; " if rotate else ""
        print(
            f"r2 {TOKEN_NAME_R2}: verification FAILED ({detail}) — no file written. {old}Revoke {access_key} by hand in the Cloudflare dashboard.",
            file=sys.stderr,
        )
        return False

    passphrase = existing.get("TOFU_STATE_PASSPHRASE") or secrets.token_urlsafe(32)
    write_env_file(
        path,
        {
            "AWS_ACCESS_KEY_ID": access_key,
            "AWS_SECRET_ACCESS_KEY": secret_key,
            "AWS_ENDPOINT_URL_S3": endpoint,
            "TOFU_STATE_PASSPHRASE": passphrase,
            "TF_ENCRYPTION": encryption_config(passphrase),
            "TOFU_STATE_ENCRYPTION_MIGRATING": encryption_config(passphrase, migrating=True),
            "TOFU_STATE_KEY_MINTED": utcnow_iso(),
        },
    )
    if not rotate:
        print(f"r2 {TOKEN_NAME_R2}: state encryption passphrase, shown once. Put its offline copy where the backup GPG key is kept before going on:")
        print(f"    {passphrase}")
    print(f"r2 {TOKEN_NAME_R2}: written to {path}, verified ({detail})")

    if rotate:
        try:
            r2_delete_token(session, account_id, existing["AWS_ACCESS_KEY_ID"])
            print(f"r2 {TOKEN_NAME_R2}: old token {existing['AWS_ACCESS_KEY_ID']} revoked")
        except RuntimeError as exc:
            print(
                f"r2 {TOKEN_NAME_R2}: new key written, but revoking old token {existing['AWS_ACCESS_KEY_ID']} failed ({exc}) — revoke it by hand.",
                file=sys.stderr,
            )
    return True


def mint_b2(*, rotate: bool = False) -> bool:
    path = config_dir() / COPY_ENV
    existing = read_env_file(path)
    if existing and not rotate:
        print(f"b2 {KEY_NAME_B2}: {path} already exists, skipping (use --rotate to replace the key)")
        return True
    if rotate and not existing:
        print(f"b2 {KEY_NAME_B2}: nothing to rotate, {path} does not exist", file=sys.stderr)
        return False

    api = b2_rotation_api()
    bucket_id = b2_lookup_bucket_id(api, bucket_name=STATE_BUCKET_B2)
    # Read back via .id_, not .application_key_id - see leaf_keys/b2.py's b2_create_leaf_key.
    key = api.create_key(capabilities=B2_LEAF_CAPABILITIES["write"], key_name=KEY_NAME_B2, bucket_id=bucket_id, valid_duration_seconds=QUARTERLY_SECONDS)
    access_key, secret_key = key.id_, key.application_key
    region = _b2_region()
    endpoint = f"https://s3.{region}.backblazeb2.com"

    ok, detail = verify_leaf_via_rclone(access_key, secret_key, endpoint, region, STATE_BUCKET_B2, "write")
    if not ok:
        old = f"Old key {existing['STATE_COPY_ACCESS_KEY_ID']} left untouched and still in use; " if rotate else ""
        print(f"b2 {KEY_NAME_B2}: verification FAILED ({detail}) — no file written. {old}Revoke {access_key} by hand in the B2 Console.", file=sys.stderr)
        return False

    write_env_file(
        path,
        {
            "STATE_COPY_ACCESS_KEY_ID": access_key,
            "STATE_COPY_SECRET_ACCESS_KEY": secret_key,
            "STATE_COPY_ENDPOINT": endpoint,
            "STATE_COPY_REGION": region,
            "STATE_COPY_BUCKET": STATE_BUCKET_B2,
            "TOFU_STATE_KEY_MINTED": utcnow_iso(),
        },
    )
    print(f"b2 {KEY_NAME_B2}: written to {path}, verified ({detail})")

    if rotate:
        old_key_id = existing["STATE_COPY_ACCESS_KEY_ID"]
        try:
            b2_delete_key(api, old_key_id)
            print(f"b2 {KEY_NAME_B2}: old key {old_key_id} revoked")
        except B2Error as exc:
            print(f"b2 {KEY_NAME_B2}: new key written, but revoking old key {old_key_id} failed ({exc}) — revoke it by hand.", file=sys.stderr)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["r2", "b2", "all"], default="all")
    parser.add_argument(
        "--rotate", action="store_true", help="Rotate: mint a new key, verify it, only then swap the file and revoke the old key. Requires --provider r2 or b2."
    )
    args = parser.parse_args()
    if args.rotate and args.provider == "all":
        parser.error("--rotate requires --provider r2 or b2")

    mint_fns = {"r2": mint_r2, "b2": mint_b2}
    targets = mint_fns if args.provider == "all" else {args.provider: mint_fns[args.provider]}
    all_ok = True
    for name, fn in targets.items():
        try:
            if not fn(rotate=args.rotate):
                all_ok = False
        except requests.HTTPError as exc:
            print(f"{name}: request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
            all_ok = False
        except B2Error as exc:
            print(f"{name}: request failed: {exc}", file=sys.stderr)
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
