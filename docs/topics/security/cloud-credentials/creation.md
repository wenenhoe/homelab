# Cloud Credential Creation — R2/B2/OCI

Scripts for minting, auditing, and verifying R2/B2/OCI credentials. What each credential is scoped to is in
[`scoping.md`](scoping.md), how they rotate in [`rotation.md`](rotation.md), and how they expire in
[`expiry.md`](expiry.md).

## Scripts

Run them from `tools/`.

| Script | Run | Authenticates with | Writes |
| :--- | :--- | :--- | :--- |
| `cloud_credentials/create_rotation_keys.py` | Rarely | B2: the master key, held in memory only. OCI: your admin config. R2: nothing, it caches a console token | The rotation credentials, in OpenBao |
| `cloud_credentials/create_leaf_keys.py` | Routinely | The cached rotation key (R2: the cached admin token, prompted for once) | The six leaf credentials, in OpenBao |
| `cloud_credentials/rotate_leaf_keys.py` | Routinely | As above | Rotates all six ([rotation](rotation.md#rotation)) |
| `cloud_credentials/create_snapshot_readonly_keys.py` | Rarely, by hand | The cached rotation credentials | Nothing: prints each credential once |
| `cloud_credentials/create_snapshot_write_keys.py` | Routinely | The cached rotation credentials | The snapshot write leaves, in OpenBao |
| `cloud_credentials/create_state_keys.py` | On the host that runs Tofu | The cached rotation credentials | Files under `~/.config/tofu/`, mode `0600` |
| `openbao_utils/audit.py` | Whenever | The cached rotation credentials | Nothing: read-only |

First-time creation, in this order:

```sh
cd tools && python3 -m cloud_credentials.create_rotation_keys --provider b2
```

```sh
# from tools/: paste alone; it waits for your admin email
read -r -p 'admin email: ' email
```

```sh
# from tools/
python3 -m cloud_credentials.create_rotation_keys --provider oci --admin-email "$email"
```

```sh
# from tools/: all three providers' leaves; asks for R2's admin token once if not cached
python3 -m cloud_credentials.create_leaf_keys
```

Re-running is safe: a credential already cached is left alone.

### create_rotation_keys.py

| Provider | What it does |
| :--- | :--- |
| B2 | Mints a rotation key that creates and deletes keys but reads and writes no backup data |
| OCI | Mints nothing. A human registers a Confidential Application in the console ([OCI](scoping.md#oci--two-separate-credentials-two-separate-auth-models)); the script prompts for and caches its client ID and secret, and bootstraps the two leaf identities' IAM policies with your admin config (`~/.oci/config`) |
| R2 | Mints nothing, since Cloudflare's API cannot create such a delegate ([R2](scoping.md#cloudflare-r2--rotation-key-exists-now-but-its-not-scoped-like-the-other-two)). `--provider r2` caches, or with `--rotate` re-caches, a Custom Token you make in the console |

### create_leaf_keys.py

It creates and rotates the six credentials of `cloud_sync` and restore discovery:
`cloudflare-r2-*`, `backblaze-b2-*` and `oci-*`, each `write` (for `cloud_sync`'s
upload leaf in `host_vars/storage.yaml`) and `read` (for restore discovery). All six
stay `source: manual` in `secret_catalog.yaml`; the script only fills them in. R2's
admin token (`_rotation-key-cloudflare-r2-token`) has a materially broader blast
radius than the other two rotation credentials
([why](scoping.md#cloudflare-r2--rotation-key-exists-now-but-its-not-scoped-like-the-other-two)).

### Snapshot credentials

- **Read-only** ([ADR 0111 (Secrets store recovery)](../../../decisions/0111-recovering-the-secrets-store-from-total-loss/revision-000.md)):
  OpenBao's break-glass restore credential, bucket-scoped on R2 and B2. Each is
  verified with a real `rclone lsjson` before it is printed, since it sits unused
  until a disaster. It is never cached; [`deployment.md`](../openbao/deployment.md)
  says where it goes.
- **Write**: the standing, quarterly-expiring leaf that
  [the backup script](../openbao/backup-restore.md) pushes snapshots with. Same
  bucket (`openbao-snapshots`), write only, cached like every leaf. `--rotate`
  verifies before it revokes.

### Tofu state keys

`create_state_keys.py` mints the two credentials of
[Tofu's remote state](../../../decisions/0103-where-tofus-state-is-held/revision-000.md): an
`opentofu-state` R2 token that reads, writes and deletes, and a write-only B2 key on
`opentofu-state-b2`. Both expire quarterly and are verified over rclone. They go to
files, not OpenBao, because Tofu has to be able to rebuild the host that runs OpenBao
([ADR 0048](../../../decisions/0048-where-tofu-credentials-live/revision-000.md)). The
R2 file also holds the state encryption passphrase, made once and shown once for its
offline copy. `--rotate` swaps a file, then revokes the old key, and keeps the
passphrase. Only the key IDs are registered, which is how the
[expiry check](expiry.md#expiry-check) sees them.

### Auditing

`audit.py --local` lists files in the controller's cache (`ansible/files/secrets/`) that
nothing in `secret_catalog.yaml` references. `--provider` lists each provider's write and
read leaves, the `openbao-snapshot-write` leaf included, and flags any not matching the
key now in OpenBao as an orphan. It deletes nothing.

```sh
cd tools && python3 -m openbao_utils.audit --local
```

```sh
# from tools/: --admin-email is for the OCI listing
python3 -m openbao_utils.audit --provider all --admin-email "$email"
```

The break-glass `openbao-snapshot-readonly` credential is never cached, so it is matched
by its provider-side name, a weaker check. With more than one key of that name, each is
marked `CHECK` instead of `ACTIVE`, and the stale ones are found in the console.

Restoring cloud_credentials' Vault state after a genuine OpenBao re-init is
`openbao_utils/restore.py`'s job — see
[`reinit-runbook.md`](../openbao/reinit-runbook.md).

## Testing

These are not Ansible roles, so Molecule's per-host model
([`molecule-testing.md`](../../testing/molecule-testing.md)) does not apply. pytest tests
under `tools/tests/cloud_credentials/` mock every provider HTTP call and `rclone` run, and
CI's `python-unit-tests` job runs them ([`pipeline.md`](../../engineering/ci/pipeline.md)):

```sh
uv run pytest tools/tests/cloud_credentials/ -n auto
```

## Where the rotation credentials live, and the libraries

Rotation keys and tokens are cached in OpenBao KV v2 at
`secret/data/cloud_credentials/rotation/*`
([ADR 0023 (Cloud credential logic reuse)](../../../decisions/0023-reusing-cloud-credential-logic-with-the-secrets-store/revision-000.md),
[ADR 0013 (Secret storage)](../../../decisions/0013-secret-storage/revision-000.md)).

The scripts use each provider's official SDK where it covers the call and raw HTTP
otherwise; no `b2` or `oci` CLI is needed. The libraries are pinned in `pyproject.toml`
([ADR 0104 (Python client libraries)](../../../decisions/0104-which-client-library-each-external-service-uses/revision-000.md)).

| Call | Client |
| :--- | :--- |
| B2 leaf and rotation keys, and `audit.py`'s listing | `b2sdk` |
| OCI leaf identities' IAM bootstrap (`rotation_keys/oci_iam.py`, a separate auth model from SCIM) | `oci.signer.Signer` |
| OCI SCIM customer-secret keys, app lookup and `audit.py`'s listing | `oci.identity_domains.IdentityDomainsClient` |
| `AppClientSecretRegenerator` | `requests`: no SDK method |
| `oci_scim.py`'s client-credentials token request | `requests`: the SDK has no bearer-token mode |
| The expiry check's Telegram `sendMessage` | `requests`: one endpoint |

`create_leaf_keys.py` and `create_rotation_keys.py` each keep their own copy of the
provider-error mapping (`_PROVIDER_ERRORS`, `_format_provider_error`), which prints a
message and raises `SystemExit(1)`. Whether it becomes one helper is undecided.
