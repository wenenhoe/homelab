# Cloud Sync — Offsite Replication to R2/B2/OCI

`cloud_sync` (`storage`-only) reads already-encrypted archives straight
out of SeaweedFS and copies them onward to R2/B2/OCI via
[rclone](https://rclone.org) `copy` — never `sync`. That distinction is
deliberate, not a naming detail: `copy` only ever adds objects on the
destination side, so nothing running on `storage` (or any app host) can
delete or overwrite what's already landed in the cloud, even if fully
compromised. `sync` would propagate a deletion outward, which is exactly
the failure mode [`disaster-recovery.md`](disaster-recovery.md)'s
Threat model section is designed against — a compromised on-prem system
shouldn't be able to touch the offsite copy. This was checked against
SeaweedFS's own native remote-sync tooling first
(`weed filer.remote.gateway`), which turned out to have `sync` semantics
itself (its own docs: local deletions propagate to the remote) — ruled
out for the same reason.

**Retention on the cloud side** is a provider-native lifecycle rule you
configure once, out-of-band, in each provider's own console — not
managed by this repo at all, and deliberately so: a homelab-side
retention job would need delete access to enforce it, which is the one
capability `cloud_sync`'s own SeaweedFS-reading identity and the
`copy`-only design both go out of their way to avoid granting anything
running on-prem.

Current values, set directly in each console:

| Cloud | Lock (immutable window) | Delete-after | Config |
| :--- | :--- | :--- | :--- |
| R2 | 29 days (Bucket Lock) | 30 days | Object Lifecycle Rules + Bucket Lock Rules |
| B2 | 28 days (Default Bucket Retention) | 30 days | Custom lifecycle rule: 29d uploading→hiding, 1d hiding→deleting |
| OCI | 5 days (Retention Rule, Unlocked) | 7 days | Retention Rules + Lifecycle Policy Rules |

Every archive's filename embeds its own upload timestamp
(`BACKUP_FILENAME` in `ansible/roles/backup_agent/templates/schedule.env.j2`)
and is never reused, so no provider's lock ever has to block an
overwrite — it's only ever guarding a delete. Each provider keeps its
lock strictly below its own delete-after (R2 1 day, B2 1 day to hiding,
OCI 2 days) — deliberate, not slack to tighten: R2's own docs confirm a
lifecycle delete against a still-locked object just defers until the
lock clears, but B2's fails outright rather than deferring, so closing
that gap on B2 specifically would start producing failed lifecycle runs
instead of merely-delayed ones.

**Which apps get which extra clouds:** `app_registry.yaml`'s
`backup.extra_cloud_targets` (e.g. minecraft's `[oci]`) — clouds beyond
SeaweedFS only; SeaweedFS itself is implicit for every backed-up app,
never listed. Defaults to `cloud_sync_default_targets`
(`host_vars/storage.yaml`, currently `[r2, b2]`) when an app doesn't
override it. Minecraft overrides to `[oci]` alone: its ~1.8GB/night
archive at 7-day retention (~13GB) would eat most of a single 10GB
R2/B2 free tier, so it gets OCI's 20GB allowance to itself instead.

**Mechanism:** a systemd timer (`cloud-sync.timer`, daily, offset ~90min
after `offsite_backup_cron` to give every backup host's own nightly run
room to land in SeaweedFS first) triggers `cloud-sync.service`
(`Type=oneshot`), which runs one container per firing — `rclone/rclone`,
looping a job manifest Ansible renders from every backup host's
`app_registry` data (cross-host, via `hostvars`, not requiring those
hosts' own plays to have run first in the same invocation). One `rclone
copy` per (app, cloud target) pair; one job failing doesn't block the
rest of that run.

**Before first use:**

- Create a bucket by hand on each of R2/B2/OCI — `homelab-backups` for
  R2/OCI (account-scoped naming, so this is fine); B2 bucket names are
  globally unique across *every* B2 account, not just yours, so
  `homelab-backups` will likely already be taken — confirmed live, not
  hypothetical, this repo's own real deploy needed `homelab-backups-b2`
  instead, hence the `-b2` suffix already baked into
  `cloud_sync_targets.b2.bucket` (`host_vars/storage.yaml`). None of
  this is Ansible-managed (same as the earlier note for SeaweedFS being
  the one exception) — a reasonable first OpenTofu project once that
  expansion starts.
- Fill in the sixteen `cloudflare-r2-*`/`backblaze-b2-*`/`oci-*` entries
  in `secrets_registry.yaml` — a write and a read credential per
  provider, plus the three shared endpoint values (account ID, B2
  region, OCI namespace/region). For B2 and OCI, `ansible/cloud_credentials/create_rotation_keys.py`
  followed by `ansible/cloud_credentials/create_leaf_keys.py` does this via each
  provider's HTTP API rather than console click-through; R2 has no
  rotation-key step at all (Cloudflare structurally can't delegate
  that capability — see `cloud-credential-creation.md`'s R2 section),
  so `create_leaf_keys.py` alone handles it, prompting for the
  master token each time it actually needs one. `bootstrap_secrets.py`
  remains the manual fallback for any of the sixteen if you'd rather
  paste in console-created values — both paths write to the same
  cache files; see
  [`cloud-credential-creation.md`](cloud-credential-creation.md)
  for exactly what each credential is scoped to, provider by provider —
  B2 and OCI both fully exclude delete from the write credential, R2
  can't (a platform limitation, not something worth re-chasing; see
  that doc's R2 section for why `copy`-vs-`sync` above is what actually
  carries the defense for R2 specifically). `backblaze-b2-region`
  specifically (B2 Console > Buckets > Bucket Details) is the one value
  here B2 assigns rather than you choosing it — get the real one from
  your own bucket, not a copied example.
- **Needs live verification, not yet confirmed:** every `rclone.conf`
  endpoint is written with its scheme (`https://`) included, not a bare
  hostname — the opposite convention from `docker-volume-backup`'s
  minio-go client elsewhere in this repo. rclone's own documented
  examples are inconsistent about this across providers; several
  non-AWS ones explicitly require the scheme, which is why it's
  included everywhere here, but this hasn't been confirmed against a
  real rclone binary. Before trusting the nightly run, verify against
  the exact image actually deployed — pulled live from
  `cloud-sync.service.j2` rather than a hardcoded tag here, so this
  command can't quietly drift from what's really running:
  ```sh
  docker run --rm \
    -v /opt/stacks/cloud-sync/rclone.conf:/config/rclone/rclone.conf:ro \
    rclone/rclone:$(grep -oP 'rclone/rclone:\K[0-9.]+' \
      ansible/roles/cloud_sync/templates/cloud-sync.service.j2) \
    lsd <name>:
  ```
  for each of the four remote names — confirm each one lists (or
  reports an empty, error-free) result.
