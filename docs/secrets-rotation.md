# Rotating a secret

Which mechanism applies depends on where the value actually comes from —
see `secrets_registry.yaml`'s `format` field for each entry
([`secrets.md`](secrets.md) covers the full generate/cache mechanism this
all builds on).

## Generated secrets (`format: hex` / `format: uuid4`)

```
ansible-playbook playbooks/rotate-secret.yaml \
  -e secret_name=<key-from-secrets_registry.yaml> -e confirm=true
```

This deletes the cached value under `ansible/files/secrets/`. It does
**not** redeploy anything itself — check the table below for which
`--limit` group the secret you rotated actually needs, then run:

```
ansible-playbook playbooks/deploy.yaml --limit <group>,localhost
```

The `,localhost` matters: `deploy.yaml`'s secrets play runs on
`hosts: localhost`, and `--limit <group>` alone excludes it, silently
skipping regeneration.

| Secret(s) | `--limit` group |
| --- | --- |
| `lldap-jwt-secret`, `lldap-key-seed`, `lldap-ldap-user-pass`, `tinyauth-ldap-observer-password`, `step-ca-password`, `step-ca-provisioner-password` | `security` |
| `shlink-api-key` | `services` |
| `seaweedfs-s3-*-services` | `services,storage` |
| `seaweedfs-s3-*-security` | `security,storage` |
| `seaweedfs-s3-*-play` | `play,storage` |
| `seaweedfs-s3-*-admin`, `seaweedfs-s3-*-cloud-sync-reader` | `storage` |

Every `seaweedfs-s3-*-<host>` row above needs `storage` alongside the
owning host, for every host in `seaweedfs_backup_hosts`
(`host_vars/storage.yaml`: `services`, `security`, `play`) — SeaweedFS's
own identity config (`s3-identity.json.j2`) is rendered on `storage`,
but pulls each host's key in via `hostvars[host].seaweedfs_s3_access_key`.
Redeploying only the owning host leaves `storage` serving the old key,
and the S3 client and server disagree.

`tinyauth-ldap-observer-password` is the one entry above that isn't just
a config re-render: `deploy.yaml`'s later "Ensure lldap's observer
account exists" play (`lldap_bootstrap`) also updates the real lldap
account to match, in the same `security` run — so a single redeploy
after rotating it is enough, no separate manual sync step.

## Manual secrets (`format: manual`)

Nothing here can generate a replacement — these are externally issued
(cloud API keys) or come from an app's own post-boot state (Beszel's
hub key/agent token). Get the new value from wherever it actually comes
from (each entry's `description` in `secrets_registry.yaml` says where),
then:

```
python3 ansible/bootstrap_secrets.py
```

## Certificate-backed material (not in `secrets_registry.yaml` at all)

lldap's LDAPS keypair isn't a registry secret — it's issued into the
`lldap_certs` volume by `lldap_cert`, and rotating it means forcing
re-issuance, not deleting a cache file:

```
ansible-playbook playbooks/volume-reset.yaml --limit security,localhost \
  -e volume_reset_app=lldap -e volume_reset_volume=certs \
  -e volume_reset_confirm=true

ansible-playbook playbooks/deploy.yaml --limit security,localhost
```

The first command empties the volume; `lldap_cert`'s own idempotency
check (`test -f /data/certs/fullchain.pem`) then fails on the second run,
triggering fresh issuance and an automatic lldap restart to pick it up.
lldap has no other consumer that needs a matching re-sync the way
tinyauth's observer password does — `tinyauth_ca_trust` trusts step-ca's
*root*, not lldap's specific leaf cert, so a rotated leaf needs no
action anywhere else as long as step-ca's own root hasn't changed (see
[`step-ca.md`](step-ca.md)).

**If the app whose volume you're resetting is currently backed up**
(has a `backup:` entry in `app_registry.yaml`), `backup_agent`'s
long-running container holds a read-only mount on that volume the whole
time it's running, which used to make the volume delete above fail with
a `409 volume is in use` even after the app's own container was torn
down. `reset_volume.yaml` now detects any other compose project still
referencing the volume, tears it down first, and brings it back up once
the volume is safe again — this happens automatically, no separate
manual step needed anymore.

## App-generated secrets (not in `secrets_registry.yaml` either)

`beszel-hub`'s KEY and TOKEN are a harder case than lldap's cert above:
they're generated inside the hub's own database on first boot, with no
way to replace just the keypair without also wiping the admin account,
monitoring history, and notification config that live in the same
volume. See [`beszel.md`](beszel.md#rotating-the-key-and-token) for the
full procedure — it's long enough, and specific enough to Beszel's own
UI, that it belongs there rather than duplicated here.
