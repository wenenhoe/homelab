# OpenBao Backup and Restore (Track A Stage 2)

A different mechanism from [`disaster-recovery.md`](disaster-recovery.md)'s
generic volume-backup pipeline — `docker/openbao/compose.yaml.j2` has no
`backup:` entry, and [`openbao.md`](openbao.md) explains why: stopping
OpenBao to tar its data volume means sealing it, which needs a manual
unseal ([0018](decisions/0018-manual-shamir-unseal.md)) on every backup
cycle. `bao operator raft snapshot save` is the backup mechanism here
instead, pushed independently to R2/B2 — see
[0019](decisions/0019-openbao-snapshot-push-standalone.md) for why the
push itself also stays out of `backup_agent`/`cloud_sync` rather than
reusing that pipeline. See
[`openbao-migration-roadmap.md`](openbao-migration-roadmap.md) for
where this sits in the overall migration.

## Why manual, not a systemd timer

A scheduled job needs a Vault token on disk to authenticate with.
Track A stage 3 (auth and least-privilege policies) minted exactly
that — `controller`'s AppRole, whose policy grants read-only on
`sys/storage/raft/snapshot` specifically for this — so lack of a safe
credential is no longer the blocker it was when this doc was first
written. What's still missing is somewhere unattended to run it from:
`controller` is the operator's own machine, never a `managed_hosts`
member, and isn't meant to run scheduled jobs at all. That's Track B's
`cd_agent` host's job
([draft](decisions/drafts/pull-based-cd-agent-not-self-hosted-github-runner.md)),
not built yet — until then, this stage proves the mechanism with a
human running it interactively, authenticating as `controller`'s
AppRole rather than the root token (see "Running a backup" below).
`ansible/roles/openbao_backup` only renders the push script and its
supporting files; it doesn't install or enable any systemd unit.

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
# From controller, using the role_id/secret_id files cached per
# openbao-auth.md's runbook - the same AppRole login docs/openbao-auth.md's
# own step 6 uses, not the root token. Prompts for secret_id (hidden
# input, read ansible/files/secrets/openbao-controller-secret-id
# yourself and paste it when asked - the script never takes it as an
# argument).
export BAO_TOKEN=$(docker/openbao/scripts/bao-login-from-controller.sh \
  "$(cat ansible/files/secrets/openbao-controller-role-id)")
echo "$BAO_TOKEN"   # copy this, then:

ssh security
export BAO_TOKEN=<paste the token from the previous step>
/opt/stacks/openbao-backup/snapshot-push.sh
```

Confirmed live against a real OpenBao 2.6.2 instance:
`bao write -f auth/approle/login role_id=<role_id> secret_id=@<file>`
returns a 200 with the client token under the `token` field
(`-field=token` extracts it cleanly, no trailing newline) — the same
shape `bao-login-from-controller.sh` already builds on, just confirmed
against the real pinned version rather than assumed. The token this
mints is short-lived (`controller`'s role config: `token_ttl=1h`), so
export it fresh each backup run rather than trying to reuse one across
sessions.

The script saves a snapshot, GPG-encrypts it (same public key as
[`disaster-recovery.md`](disaster-recovery.md)'s
`backup-gpg-public-key.asc`, independently of Vault's own encryption),
and pushes it to both providers. `BAO_TOKEN` only ever passes through
`docker exec -e` from your shell's environment — never written to a
file or passed as an argument.

**Version note — needs a pass:** `bao operator raft snapshot save`'s
behavior (described below) was confirmed live against a real backup
run, but against the `2.5.4` image that was pinned at the time —
`docker/openbao/compose.yaml.j2` now pins `2.6.2`, and that confirmation
has not been re-run since the pin moved. The restore-side behavior
below (`-force`, the reseal, the old token going invalid) is still only
confirmed against a v2.2.0 spike instance, never against either `2.5.4`
or `2.6.2` directly — v2.5.4's release assets weren't reachable to test
against outside `security` itself, and the same is true of `2.6.2`
without repeating the exercise on a real host. This matters more than a
version-number footnote: `2.6.2` is also where `generate-root`'s
authenticated-endpoint behavior changed (see
[ADR 0025](decisions/0025-openbao-reinit-with-standing-vault-bootstrap-role.md)'s
Context), so a version this far off isn't guaranteed to behave like
`2.5.4` did here either. Confirm both the snapshot-save and restore-side
behavior against the real `2.6.2` image during the next restore drill,
before trusting either paragraph below as still accurate.

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
  also stops working once the restore completes; `controller`'s
  AppRole (part of the restored data itself, confirmed present since
  Track A stage 3 landed) is what's valid against the restored data,
  not a root token — see `openbao-vault-bootstrap.md` if a step ever
  needs more than `controller`'s own read access.

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
6. Authenticate as `controller` — its AppRole config is part of the
   restored data, so this also proves the restore brought back more
   than just secret values — and read back a known secret path to
   confirm the restore actually worked, not just that the command
   exited 0. No root token or `vault-bootstrap` needed for this: a
   plain read is exactly what `controller`'s own policy already
   grants.

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
  still needs a human to export `BAO_TOKEN`. The login mechanics are
  now confirmed live (see
  [`docker/openbao/scripts/bao-login.sh`](../docker/openbao/scripts/bao-login.sh):
  `-field=token` prints the raw `client_token` and nothing else, and
  `@-` is *not* stdin shorthand for this `bao` build — a real temp
  file is required). Writing that into `snapshot-push.sh` itself, and
  adding the systemd timer, is still open — not a large change now
  that the shape is known, just not done.
