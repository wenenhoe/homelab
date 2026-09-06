# OpenBao Backup and Restore (Track A Stage 2)

A different mechanism from [`disaster-recovery.md`](disaster-recovery.md)'s
generic volume-backup pipeline — `docker/openbao/compose.yaml.j2` has no
`backup:` entry, and [`openbao.md`](openbao.md) explains why: stopping
OpenBao to tar its data volume means sealing it, which needs a manual
unseal ([0021](decisions/0021-manual-shamir-unseal.md)) on every backup
cycle. `bao operator raft snapshot save` is the backup mechanism here
instead, pushed independently to R2/B2 — see
[0023](decisions/0023-openbao-snapshot-push-standalone.md) for why the
push itself also stays out of `backup_agent`/`cloud_sync` rather than
reusing that pipeline. See
[`openbao-migration-roadmap.md`](openbao-migration-roadmap.md) for
where this sits in the overall migration.

## Why manual, not a systemd timer

A scheduled job needs a Vault token on disk to authenticate with. Right
now the only one that exists is the initial root token, and
[`openbao.md`](openbao.md)'s own Init runbook is explicit that it must
never be written to a file on `security`. Track A stage 3 (auth and
least-privilege policies) is what mints a credential actually safe to
leave for an unattended job; until then, this stage proves the
mechanism with a human running it interactively — same reasoning
[`openbao.md`](openbao.md) already gives for why init/unseal are
runbooks, not scripts. `ansible/roles/openbao_backup` only renders the
push script and its supporting files; it doesn't install or enable any
systemd unit.

## Push credential

`ansible/cloud_credentials/create_snapshot_write_keys.py` mints a
standing, quarterly-rotating, no-delete write leaf on both R2 and B2,
scoped to the `openbao-snapshots` bucket — a different credential from
[0017](decisions/0017-openbao-bootstrap-secret-split.md)'s break-glass
**read-only** restore key, which stays reserved for actual disaster
recovery and is never cached to disk. See
[`cloud-credential-creation.md`](cloud-credential-creation.md) for how
it's minted and rotated.

## Before first use

Create the `openbao-snapshots` bucket by hand on **both** R2 and B2 —
same as [`cloud-sync.md`](cloud-sync.md)'s own bucket, none of this is
Ansible-managed. Do this before minting either credential above, not
after: `create_snapshot_readonly_keys.py`'s own failure message already
assumes the bucket exists first.

B2 bucket names are globally unique across *every* B2 account, not just
yours — `cloud-sync.md`'s own bucket hit exactly this and needed a
`-b2` suffix. If `openbao-snapshots` is taken on B2, pick a different
name, update `SNAPSHOT_BUCKET_B2` in
`create_snapshot_readonly_keys.py` (both scripts import it from there)
and `openbao_snapshot_targets.b2.bucket` in `host_vars/security.yaml`,
then (re-)mint both credentials against the new name.

The write leaf has no bucket-admin capability on either provider (see
below) — `rclone copy` against a bucket that doesn't exist yet fails
with an `AccessDenied` on `CreateBucket`, not a clearer "bucket not
found," since rclone's own pre-flight check is what's being denied.

## Running a backup

```sh
ssh security
export BAO_TOKEN=<current root token, from the break-glass password-manager entry>
/opt/stacks/openbao-backup/snapshot-push.sh
```

The script saves a snapshot, GPG-encrypts it (same public key as
[`disaster-recovery.md`](disaster-recovery.md)'s
`backup-gpg-public-key.asc`, independently of Vault's own encryption),
and pushes it to both providers. `BAO_TOKEN` only ever passes through
`docker exec -e` from your shell's environment — never written to a
file or passed as an argument.

**Version note:** `bao operator raft snapshot save`'s behavior
(described below) is now confirmed live against the actual pinned
`2.5.4` image on `security` — a real backup has run successfully. The
restore-side behavior below (`-force`, the reseal, the old token going
invalid) is still only confirmed against a v2.2.0 spike instance, not
`2.5.4` — v2.5.4's release assets weren't reachable to test against
directly outside `security` itself. Worth confirming during the
restore drill itself, since that's the first time this repo's tooling
will exercise it against the real pinned version.

## `bao` CLI behavior this script and the restore drill depend on

Confirmed against a real running instance, not inferred from docs:

- `bao operator raft snapshot save <path>` takes a plain positional
  path, prints nothing on success, and produces a gzip-compressed
  file.
- Plain `bao operator raft snapshot restore <path>` **fails** —
  `could not verify hash file, possibly the snapshot is using a
  different set of unseal keys` — on any target whose keyring doesn't
  already match the snapshot's. This is not an edge case for the drill
  below: a freshly-initialized throwaway host *always* has different
  keys, so the plain restore path never works for real disaster
  recovery.
- `bao operator raft snapshot restore -force <path>` is the actual
  mechanism — a documented flag (`bao operator raft snapshot restore
  -h`, easy to miss), not an undocumented workaround.
- **After a forced restore, OpenBao reseals itself.** It must be
  unsealed again using the *original snapshot's* Shamir shares — not
  the throwaway host's own freshly-generated ones from its local
  `bao operator init`. The throwaway host's own pre-restore root token
  also stops working once the restore completes; only the original
  bundle's root token (or, once Track A stage 3 lands, an AppRole
  login) is valid against the restored data.

## Restore drill

On a throwaway host — burn it afterward, don't reuse it:

1. Install OpenBao (same version as the `security` deploy), start it
   with a fresh raft config, run `bao operator init` on it, then unseal
   it with its own fresh keys — required before the restore endpoint is
   even reachable (a sealed node returns `503`, not a clearer error).
   Its own keys and root token are used once more, in the next step,
   then discarded.
2. Fetch the latest snapshot from R2 or B2 using the break-glass
   **read-only** credential
   ([`create_snapshot_readonly_keys.py`](../ansible/cloud_credentials/create_snapshot_readonly_keys.py)) —
   not the write leaf above, which can't read.
3. Decrypt it with the offline GPG private key
   ([`disaster-recovery.md`](disaster-recovery.md#encryption)).
4. Authenticate with the throwaway host's own root token (from step 1)
   and run `bao operator raft snapshot restore -force <path>` — a
   token is required even against a target with nothing real on it
   yet. The node reseals itself immediately afterward; both the
   throwaway host's root token and its own unseal keys become useless
   against the restored data from this point on.
5. Unseal again using the break-glass bundle's *original* Shamir
   shares (from the password manager, not this host's own `init`
   output).
6. Authenticate with the break-glass root token and read back a known
   secret path to confirm the restore actually worked, not just that
   the command exited 0.

Only after this passes for real does Track A stage 2 count as proven —
see the roadmap's own stage-status table.

## Open follow-ups

- No local retention on the `security`-side staging directory
  (`{{ compose_deploy_dir }}/openbao-backup/staging`) — encrypted
  snapshots accumulate there until deleted by hand. Low priority: the
  cloud copies, not this host's own, are the actual recovery path.
- Track A stage 3 ([`openbao-auth.md`](openbao-auth.md)) grants the
  `controller` policy read access to `sys/storage/raft/snapshot`, but
  `snapshot-push.sh` itself hasn't been changed to use it yet — it
  still needs a human to export `BAO_TOKEN`. The exact output shape of
  `bao write -f auth/approle/login role_id=... secret_id=...`
  (`-format=json`'s field names, and how cleanly that composes with
  the existing `docker exec -e` pattern) hasn't been checked against a
  live instance. That's a time-boxed spike before writing the
  login-and-save logic into the script and adding a systemd timer for
  it, not a large change once answered — tracked here rather than
  guessed at.
