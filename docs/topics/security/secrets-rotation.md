# Rotating a secret

Which mechanism applies depends on the entry's `source` in `secret_catalog.yaml`
([`secrets.md`](secrets.md) covers generation and storage).

| Kind | How to change it | Afterwards |
| :--- | :--- | :--- |
| `hex`, `uuid4` | [`rotate-secret.yaml`](#generated-secrets-source-hex--source-uuid4) | Redeploy the group in the table below. |
| `manual` | [Overwrite the stored value](#manual-secrets-source-manual) | Redeploy the hosts that render it. |
| Cloud leaf credentials | [`create_leaf_keys.py --rotate`](#cloud-leaf-credentials) | Redeploy `storage` for a write leaf only. |
| lldap's certificate | [Reset its volume](#certificate-backed-material-not-in-secret_catalogyaml-at-all) | The same redeploy issues a new one. |
| Beszel's key and token | [Its own procedure](#app-generated-secrets-not-in-secret_catalogyaml-either) | |

## Generated secrets (`source: hex` / `source: uuid4`)

```sh
# paste alone; it waits for the secret's key in secret_catalog.yaml
read -r -p 'secret name: ' name
```

```sh
# from ansible/
ansible-playbook playbooks/rotate-secret.yaml \
  -e secret_name="$name" -e confirm=true
```

Every `hex`/`uuid4` entry is `store: openbao`. The playbook writes a fresh value in place with
`cas=<current version>`: an update, because `controller`'s AppRole has no `delete` on
`secret/data/hosts/*` ([`auth.md`](openbao/auth.md)'s runbook proves it). The previous value stays
in KV version history. It redeploys **nothing**; pick the `--limit` group from the table below, then
run:

```sh
# paste alone; it waits for the --limit group from the table below
read -r -p 'group: ' group
```

```sh
ansible-playbook playbooks/deploy.yaml --limit "$group,localhost"
```

The `,localhost` matters: `deploy.yaml`'s secrets play runs on
`hosts: localhost`, and `--limit <group>` alone excludes it, silently
skipping regeneration.

| Secret(s) | `--limit` group |
| --- | --- |
| `lldap-jwt-secret`, `lldap-key-seed`, `lldap-ldap-user-pass`, `tinyauth-ldap-observer-password` | `security` |
| `shlink-api-key` | `services` |
| `seaweedfs-s3-*-services` | `services,storage` |
| `seaweedfs-s3-*-security` | `security,storage` |
| `seaweedfs-s3-*-play` | `play,storage` |
| `seaweedfs-s3-*-admin`, `seaweedfs-s3-*-cloud-sync-reader` | `storage` |

A `seaweedfs-s3-*-<host>` row names `storage` too because SeaweedFS's identity config
(`s3-identity.json.j2`) is rendered there from each host's key via `hostvars`. Redeploying only the
owning host leaves client and server disagreeing.

`tinyauth-ldap-observer-password` is the one entry above that isn't just
a config re-render: `deploy.yaml`'s later "Ensure lldap's observer
account exists" play (`lldap_bootstrap`) also updates the real lldap
account to match, in the same `security` run — so a single redeploy
after rotating it is enough, no separate manual sync step.

**Do not rotate `step-ca-password` or `step-ca-provisioner-password`.** The CA's keys and the JWK
provisioner key are encrypted with them once, at the first `step ca init`
(`docker/step-ca/scripts/entrypoint.sh`). After a rotation and redeploy step-ca cannot start, and
OpenBao's certificate renewal and the secrets role's root-certificate fetch depend on it. Changing
either means re-encrypting the keys first, which nothing here does.

## Manual secrets (`source: manual`)

Nothing here generates a replacement: get the new value from where the entry's `description` in
`secret_catalog.yaml` says. `openbao_utils.bootstrap` does not replace it, since it leaves any entry
that already has a value untouched. Overwrite the stored value instead, as `controller`:

```sh
# controller: paste alone; it opens a shell and waits for the secret_id
cd tools && python3 -m openbao_utils.shell "$(cat ../ansible/files/secrets/openbao-controller-role-id)"
```

```sh
# inside that shell: paste alone; it waits for the entry's scope and catalog key
read -r -p 'scope: ' scope; read -r -p 'catalog key: ' key
```

```sh
# same shell: paste alone; it waits for the new value, hidden
read -rs -p 'new value: ' value; echo; printf '%s' "$value" | bao kv put -mount=secret "$scope/$key" value=-; unset value
```

Then `exit`, and redeploy the hosts that render it. A file-cache entry is overwritten as shown under
[Bootstrapping manual secrets](secrets.md#bootstrapping-manual-secrets).

## Cloud leaf credentials

R2, B2 and OCI leaves have one scripted path that creates the new key, verifies it over the same
route production uses, and only then revokes the old one:

```sh
# paste alone; it waits for the provider (r2, b2 or oci) and the leaf (write, read or both)
read -r -p 'provider: ' provider; read -r -p 'leaf: ' leaf
```

```sh
cd tools
python3 -m cloud_credentials.create_leaf_keys --provider "$provider" --rotate "$leaf"
```

[`cloud-credentials/rotation.md`](cloud-credentials/rotation.md#rotation) covers what happens when
verification fails, and why R2's cached rotation credential has a broader blast radius than B2's or
OCI's, which is accepted.

| Leaf | Consumer | Redeploy |
| :--- | :--- | :--- |
| Write | The `cloud_sync` timer on `storage`, rendered by `deploy.yaml`. | Needed (below). On the CD agent the `rotation` job rotates the leaves monthly and `redeploy-storage` does it ([`cd-agent-host.md`](../deploy/cd-agent-host.md#applying-it)). |
| Read | `restore_discovery`, which runs on `controller` and renders from the current values every time. | None. |

```sh
# from ansible/, after rotating a write leaf
ansible-playbook playbooks/deploy.yaml --limit storage,localhost
```

After a rotation, or a failed one that may have left an unverified key behind,
`openbao_utils/audit.py --provider <r2|b2|oci>` lists what is on the provider's console and flags
anything that doesn't match what is stored.

## Certificate-backed material (not in `secret_catalog.yaml` at all)

lldap's LDAPS keypair isn't a catalog secret — it's issued into the
`lldap_certs` volume by `step_ca_cert`, and rotating it means forcing
re-issuance, not deleting a cache file:

```sh
ansible-playbook playbooks/volume-reset.yaml --limit security,localhost \
  -e volume_reset_app=lldap -e volume_reset_volume=certs \
  -e volume_reset_confirm=true

ansible-playbook playbooks/deploy.yaml --limit security,localhost
```

The first command empties the volume; `step_ca_cert`'s own idempotency
check (`test -f /data/certs/fullchain.pem`) then fails on the second run,
triggering fresh issuance and an automatic lldap restart to pick it up.
lldap has no other consumer that needs a matching re-sync the way
tinyauth's observer password does — `tinyauth_ca_trust` trusts step-ca's
*root*, not lldap's specific leaf cert, so a rotated leaf needs no
action anywhere else as long as step-ca's own root hasn't changed (see
[`step-ca.md`](../services/step-ca.md)).

A backed-up app's volume is also mounted read-only by `backup_agent`'s container.
`reset_volume.yaml` finds any other compose project using the volume, takes it down and brings it
back once the volume is safe, so no manual step is needed.

## App-generated secrets (not in `secret_catalog.yaml` either)

`beszel-hub`'s KEY and TOKEN are generated inside the hub's database on first boot, and replacing
the keypair means wiping the admin account, history and notification config in the same volume. See
[`beszel.md`](../monitoring/beszel.md#rotating-the-key-and-token) for the full procedure — it's long enough, and specific enough to Beszel's own
UI, that it belongs there rather than duplicated here.
