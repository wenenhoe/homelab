# OpenBao Backup and Restore

A different mechanism from [`disaster-recovery.md`](disaster-recovery.md)'s
generic volume-backup pipeline — `docker/openbao/compose.yaml.j2` has no
`backup:` entry, and [`openbao.md`](openbao.md) explains why: stopping
OpenBao to tar its data volume means sealing it, which needs a manual
unseal ([0018](decisions/0018-unsealing-the-secrets-store-after-restart/revision-000.md)) on every backup
cycle. `bao operator raft snapshot save` is the backup mechanism here
instead, pushed independently to R2/B2 — see
[0019](decisions/0019-openbao-offsite-snapshot-path/revision-000.md) for why the
push itself also stays out of `backup_agent`/`cloud_sync` rather than
reusing that pipeline.

## Why manual, not a systemd timer

A scheduled job needs a Vault token on disk to authenticate with.
[`openbao-auth.md`](openbao-auth.md)'s policy for `controller`'s
AppRole grants read-only on `sys/storage/raft/snapshot` specifically
for this. What's still missing is somewhere unattended to run it from:
`controller` is the operator's own machine, never a `managed_hosts`
member, and isn't meant to run scheduled jobs at all. That's the
[CD agent project](projects/cd-agent.md)'s `cd_agent` host's job
([working decision](decisions/0044-prod-automation-trigger-and-execution/revision-000.md)),
not built yet — for now, this proves the mechanism with a
human running it interactively, authenticating as `controller`'s
AppRole rather than the root token (see "Running a backup" below).
`tools/openbao_utils/scripts/snapshot-push.sh` is a plain script, not
installed or enabled as a systemd unit anywhere.

## Push credential

`tools/cloud_credentials/create_snapshot_write_keys.py` mints a
standing, quarterly-rotating, no-delete write leaf on both R2 and B2,
scoped to the `openbao-snapshots` bucket — a different credential from
[0017](decisions/0017-recovering-the-secrets-store-from-total-loss/revision-000.md)'s break-glass
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
and the hardcoded `openbao-snapshots` bucket name in
`tools/openbao_utils/scripts/snapshot-push.sh`'s `rclone copy` calls,
then (re-)mint both credentials against the new name.

The write leaf has no bucket-admin capability on either provider (see
below) — `rclone copy` against a bucket that doesn't exist yet fails
with an `AccessDenied` on `CreateBucket`, not a clearer "bucket not
found," since rclone's own pre-flight check is what's being denied.

## Running a backup

```sh
tools/openbao_utils/scripts/snapshot-push.sh "$(cat ansible/files/secrets/openbao-controller-role-id)"
```

From `controller`, using the same `controller` AppRole `role_id`
cached per [`openbao-auth.md`](openbao-auth.md)'s runbook. Prompts for
`secret_id` (hidden input, read
`ansible/files/secrets/openbao-controller-secret-id` yourself and
paste it when asked — the script never takes it as an argument). One
process end to end: logs in over real TLS, saves the snapshot,
GPG-encrypts it (same public key as
[`disaster-recovery.md`](disaster-recovery.md)'s
`backup-gpg-public-key.asc`, independently of Vault's own encryption),
pushes it to both R2 and B2, and revokes the token — all from one
`mktemp -d` scratch directory removed when the script exits, nothing
left behind on `controller` either way.

Confirmed live against a real OpenBao 2.6.2 instance:
`bao write -field=token auth/approle/login role_id=<role_id>
secret_id=@<file>` returns a 200 with the client token under the
`token` field (no trailing newline) — the shape
`snapshot-push.sh` builds on directly. The token this mints is
short-lived (`controller`'s role config: `token_ttl=1h`), which is why
the script logs in fresh on every run rather than trying to reuse one
across invocations.

`BAO_TOKEN` only ever lives in this one script's own process
environment — never written to a file, never passed as a command-line
argument to anything it calls. `bao operator raft snapshot save`
inherits it the same way any other native `bao` invocation does.

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
[ADR 0025](decisions/0025-admin-capability-without-a-standing-root-token/revision-000.md)'s
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
  AppRole (part of the restored data itself) is what's valid against
  the restored data, not a root token — see
  `openbao-vault-bootstrap.md` if a step ever needs more than
  `controller`'s own read access.

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
   ([`create_snapshot_readonly_keys.py`](../tools/cloud_credentials/create_snapshot_readonly_keys.py)) —
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
