# Cloud Credential Creation — R2/B2/OCI

Scripts for minting, auditing, and verifying R2/B2/OCI credentials. What each credential is scoped to is in
[`scoping.md`](scoping.md), how they rotate in [`rotation.md`](rotation.md), and how they expire in
[`expiry.md`](expiry.md).

The scripts:

- **`tools/cloud_credentials/create_rotation_keys.py`** — run rarely.
  For B2, takes the master credential in memory only (never written to
  disk, never logged) and uses it to mint a narrower **rotation key**:
  scoped to creating/deleting keys, not to reading or writing backup
  data itself. For OCI, there's no credential to mint — a human
  registers a Confidential Application by hand in Console once (see
  [the OCI section](scoping.md#oci--two-separate-credentials-two-separate-auth-models)), and this script prompts for and caches its client
  ID/secret, alongside bootstrapping the two leaf identities' classic
  IAM policies with your personal admin config (`~/.oci/config`) —
  unrelated to the Confidential Application, still needed, see
  [the OCI section](scoping.md#oci--two-separate-credentials-two-separate-auth-models) for why. For R2, there's nothing to mint either — Cloudflare
  has no way to create such a delegate credential via its API at all
  (confirmed live, see [the R2 section](scoping.md#cloudflare-r2--rotation-key-exists-now-but-its-not-scoped-like-the-other-two)) — `--provider r2` here only
  caches (or re-caches, via `--rotate`) the Custom Token a human
  creates in the Console. Whatever gets cached either way is what
  `create_leaf_keys.py` actually reads.
- **`tools/cloud_credentials/create_leaf_keys.py`** — run routinely.
  This is what actually creates/rotates the 6 `cloud_sync`/
  restore-discovery credentials (`cloudflare-r2-write-*`/`-read-*`,
  `backblaze-b2-write-*`/`-read-*`, `oci-write-*`/`-read-*` in
  `secret_catalog.yaml` — **write** for `cloud_sync`'s own upload leaf
  in `host_vars/storage.yaml`, **read** for the controller-side
  restore-discovery script). B2 and OCI authenticate with their cached
  rotation key; R2 authenticates with its own cached admin token
  (`_rotation-key-cloudflare-r2-token` — prompted for once, then reused
  — see [R2's section](scoping.md#cloudflare-r2--rotation-key-exists-now-but-its-not-scoped-like-the-other-two) for why this one is a materially broader-blast-radius
  credential than the other two's). All six leaf credentials stay
  `source: manual` in the catalog; this script is just an automated
  way to fill them in.
- **`openbao_utils/audit.py`** — run whenever, read-only. `--local`
  diffs `ansible/files/secrets/` against `secret_catalog.yaml` to
  flag cache files nothing currently references (e.g. leftover from a
  naming change). `--provider {oci,b2,r2,all}` lists each provider's
  actual write/read-leaf credentials — including the standing
  `openbao-snapshot-write` leaf — and flags any not matching the
  current Vault-backed cache as an orphan — e.g. a key from an
  interrupted rotation never cleaned up on the provider's side. The one
  exception: ADR 0017's break-glass `openbao-snapshot-readonly`
  credential is never cached anywhere by design, so it's matched by its
  known provider-side name instead of a cache lookup — a weaker check,
  but this tool only ever flags, never deletes. Flags only; deleting
  anything it finds is a separate, deliberate step.
- **`tools/cloud_credentials/create_snapshot_readonly_keys.py`** —
  run rarely, by hand. Mints the read-only, bucket-scoped R2/B2
  credentials [ADR 0017](../../../decisions/0017-recovering-the-secrets-store-from-total-loss/revision-000.md)
  calls for — OpenBao's own break-glass snapshot-restore credential,
  not a `cloud_sync` leaf. Verifies each one via a real `rclone lsjson`
  against its actual bucket before printing it — same discipline
  `create_leaf_keys.py --rotate` already applies before trusting a new
  leaf, worth it here too since this credential otherwise sits unused
  until an actual disaster. Prints each credential once instead of
  caching it to OpenBao; see
  [`openbao.md`](../openbao.md) for where it goes from there.
- **`tools/cloud_credentials/create_snapshot_write_keys.py`** — run
  routinely, same cadence as `create_leaf_keys.py`. Mints the standing,
  quarterly-expiring write leaf the backup script in
  [`openbao-backup-restore.md`](../openbao-backup-restore.md) pushes
  snapshots with — a different credential from the read-only one just
  above, scoped to the same `openbao-snapshots` bucket but write-only
  (no `deleteFiles`/admin capability, same shape as `cloud_sync`'s own
  write leaves). Cached to OpenBao like every other leaf here, unlike
  the break-glass credential. Supports `--rotate`, same
  verify-before-revoke behavior as `create_leaf_keys.py --rotate`.

Restoring cloud_credentials' Vault state after a genuine OpenBao re-init is
`openbao_utils/restore.py`'s job — see
[`openbao-reinit-runbook.md`](../openbao-reinit-runbook.md).

**Testing:** none of these are an Ansible role, so Molecule's per-host
model (`docs/topics/engineering/molecule-testing.md`) doesn't apply. `ansible/tests/`
holds pytest tests — every provider HTTP call and `rclone` invocation
mocked — run via `uv run pytest ansible/tests/ -v` and wired into CI as
`pr-checks.yml`'s
`python-unit-tests` job (see `docs/topics/engineering/ci/pipeline.md`).

Rotation keys/tokens (all three providers) are cached to OpenBao KV v2,
at `secret/data/cloud_credentials/rotation/*` — see
[ADR 0023](../../../decisions/0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md) for why
this repointed the existing per-provider Python rather than replacing
it, and [ADR 0013](../../../decisions/0013-secret-storage/revision-000.md)
for the earlier decision that started it in a file cache in the first
place.

```sh
cd tools
python3 -m cloud_credentials.create_rotation_keys --provider b2
python3 -m cloud_credentials.create_rotation_keys --provider oci --admin-email you@example.com
python3 -m cloud_credentials.create_leaf_keys   # all three leaves; prompts for R2's admin token once, if not yet cached
```

Safe to re-run either script — a credential whose cache files already
exist is left alone. Both use each provider's official SDK where one
covers the call and raw HTTP otherwise, no `b2`/`oci` CLI binary
required — `requests`, `oci`, and `b2sdk` are all pinned in
`pyproject.toml`. `oci` supplies both `oci.signer.Signer` (OCI's
leaf-identity IAM bootstrap, `rotation_keys/oci_iam.py` — a separate,
unrelated auth model from SCIM) and, as of
[`cloud-credentials-hardening.md`](../../../projects/cloud-credentials-hardening.md)'s
Stage 2, `oci.identity_domains.IdentityDomainsClient` for the SCIM
customer-secret-key and Apps-lookup calls (`AppClientSecretRegenerator`
has no SDK method and stays on raw `requests` regardless). `b2sdk`
covers B2's leaf/rotation key create/delete/list calls as of that same
project's Stage 3.
