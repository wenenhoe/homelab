# Secrets

For the offsite-backup S3 credentials specifically, see
[`disaster-recovery.md`](disaster-recovery.md).

Every value this repo needs but doesn't want hardcoded is resolved once
and cached by the `secrets` role (`ansible/roles/secrets/`), driven by a
central registry (`ansible/inventory/group_vars/all/secrets_registry.yaml`).
It runs as `deploy.yaml`'s Play 0, tagged `always`, `gather_facts: false`
— before Play 1, since `ansible_host` itself resolves through a secret
(`main_domain`) and Play 1's implicit fact-gathering needs a live
connection first.

Every secret lives in OpenBao (Track A stage 4) except three permanent
exceptions that stay in the controller-side file cache instead:
`main-domain` and the `openbao-controller-role-id`/`-secret-id` AppRole
credential — because resolving any of them is a prerequisite for
reaching Vault at all. Every registry entry's `vault_scope` says where
in Vault it lives, including every `cloudflare-r2-*`/`backblaze-b2-*`/
`oci-*` entry (`vault_scope: cloud_credentials/leaf`, the same top-level
path `ansible/cloud_credentials/*.py` itself writes to — see
`cache.py`'s own `scoped()`, not a `hosts/*`-scoped path). See `secrets_registry.yaml`'s own header comment and
[ADR 0021](decisions/0021-vault-path-convention-hosts-all-for-global-secrets.md)
for the full picture.

No template should call `lookup('password', ...)` / `lookup('pipe', ...)`
directly, and `deploy.yaml` should never grow a new `vars_prompt` entry —
any new secret or config value goes through the registry instead:

1. Add an entry to `secrets_registry.yaml`, with a `vault_scope`
   (`hosts/<host>` if it's referenced from that host's own
   `host_vars/<host>.yaml`, `hosts/all/<concern>` if it's referenced
   from `group_vars/all/main.yaml` — see [ADR 0021](decisions/0021-vault-path-convention-hosts-all-for-global-secrets.md)):
   ```yaml
   secrets_registry:
     my-new-thing: { format: hex, length: 32, vault_scope: hosts/security }
   ```
2. Reference it from a plain var in `group_vars/all/main.yaml`:
   ```yaml
   my_new_thing: "{{ secrets_generated['my-new-thing'] }}"
   ```
   Unless it's only ever needed on one specific host — no other host's
   template or role references it — in which case put the var in that
   host's own `host_vars/<host>.yaml` instead of `main.yaml`. Templates
   reference it identically either way (`{{ my_new_thing }}`); this is
   purely about where the value is visible, not how it's used. Check
   for cross-host references before choosing `host_vars` — e.g.
   `tinyauth_host` looks single-host at a glance but every host's Caddy
   config references it for forward-auth, so it stays in `main.yaml`;
   `step_ca_password` (the server's own bootstrap secret) has no such
   reference and lives in `host_vars/security.yaml` instead. See
   `ansible/inventory/host_vars/{storage,security,services}.yaml` for
   more examples of the split.
3. Use `{{ my_new_thing }}` in the app's `configs/*.j2` template, with
   `no_log: true` on its `app_registry` entry if it's a real secret (see
   `no_log: true` below). Never in `compose.yaml` itself, even though it
   can also reference Ansible vars now — its deploy task has no
   per-app `no_log:`/mode handling, unlike `configs` (see
   [`adding-an-app.md`](adding-an-app.md)).

## Three formats

| Format | Used for | Mechanism |
| :--- | :--- | :--- |
| `hex` | Most secrets | Vault-backed only, since Track A stage 6 retired the file-cache-backed generation path: check-then-write against KV v2 with `cas=0`, value generated via `python3 -c "import secrets; ..."` — see `ensure_secret.yaml`/`generate_vault_value.yaml`. |
| `uuid4` | `shlink-api-key` only | Vault-backed only, same reasoning as `hex` above — this format always generates via `python3 -c "import uuid; print(uuid.uuid4())"`, since `lookup('password')`'s `chars=` can't produce a structurally valid UUID4. |
| `manual` | Externally-issued credentials and plain config Ansible can't generate (e.g. the DigitalOcean API key, Beszel's post-boot key/token) | No generation step. Vault-backed entries (everything except the three permanent exceptions) are populated by `create_leaf_keys.py`/`create_rotation_keys.py` for cloud credentials, or `bootstrap_secrets.py` for everything else, before they're first read; missing → the play fails loudly naming the OpenBao path and pointing at the right script. File-cache-backed entries (`main-domain`, the controller AppRole pair) work the same as before: missing cache file → same loud failure, naming the file to create by hand. Present-but-empty is valid (not an error) for entries marked `allow_blank: true`, which lets Beszel's two values start blank either way. |

## Bootstrapping manual secrets

Before your first `deploy.yaml` run:

```sh
python3 ansible/bootstrap_secrets.py
```

Prompts for every `manual` entry that isn't already set (masked input
for anything marked `sensitive: true`), skipping entries that already
have a value. Safe to re-run. Vault-backed entries need OpenBao
reachable and the controller AppRole already provisioned
([`openbao-auth.md`](openbao-auth.md)'s runbook) before this script can
do anything with them; it fetches step-ca's root cert fresh each run to
validate OpenBao's TLS cert, the same mechanism
[ADR 0022](decisions/0022-controller-vault-tls-trust-via-per-run-fetched-root-cert.md)
uses from Ansible. To set a file-cache-backed value without the script:

```sh
printf '%s' '<value>' > ansible/files/secrets/<registry-key>
chmod 600 ansible/files/secrets/<registry-key>
```

Beszel's key/token can't be known ahead of time — see the manual
redeploy sequence in [`beszel.md`](beszel.md).

The R2/B2/OCI entries are `manual` too, but Vault-backed
(`vault_scope: cloud_credentials/leaf`) and deliberately excluded from
`bootstrap_secrets.py`'s own prompting — `create_rotation_keys.py`/
`create_leaf_keys.py` own them, with real provider-side verification
`bootstrap_secrets.py`'s generic prompt-and-write can't do. See
[`cloud-credential-creation.md`](cloud-credential-creation.md) for how
to create them instead.

## Where secrets live

Vault-backed: OpenBao, at `secret/data/{{ vault_scope }}/<registry-key>`
(mount `secret`, KV v2). File-cache-backed: `ansible/files/secrets/<registry-key>`
on the controller, one file per secret, gitignored, never committed.
Either way, target hosts only ever receive the rendered config the
value ends up in — never the registry key or its storage location.

**Rotating a credential**: see [`secrets-rotation.md`](secrets-rotation.md)
for the `rotate-secret.yaml` playbook and exactly which host(s) each
secret needs redeployed — the per-host SeaweedFS identity keys in
particular need both the owning host *and* `storage` redeployed, not
just one, since SeaweedFS's own identity config
([`disaster-recovery.md`](disaster-recovery.md)) is rendered on
`storage` but pulls each host's key in via `hostvars`.

## Why S3 credentials need a controller-side cache

`docker-volume-backup`'s S3 client (`backup_agent` hosts) and SeaweedFS's
own identity config (`storage`) are rendered independently on different
hosts. Without a shared cache, each would generate its own value and
permanently disagree. Every secret goes through the same cache for
consistency, even ones like `lldap`'s that are only ever rendered on one
host.

## `no_log: true`

Every `app_registry` entry whose `configs` render a real secret (API key,
token, password) sets `no_log: true` — and so does anything that reveals
the actual configured domain (a routed URL, an LDAP base DN, a DNS name
list), even though it isn't a credential. A bare timezone or a short
host label that carries no domain information doesn't need it. See
[`adding-an-app.md`](adding-an-app.md) for the quick check on whether a
value counts. Without `no_log: true`, `ansible-playbook --diff` prints
the new value in plaintext on any task where content changes —
including the first deploy, since a not-yet-existing file still counts
as a diff. `no_log: true` suppresses this (including on task failure)
while still reporting `changed: true`.

## `force: false`

Every config in this registry defaults to `force: true` (overwrite on
drift) — this repo is the source of truth. Reserve `force: false` for a
destination the *app itself* writes back to after Ansible first renders
it, where overwriting would destroy state no template can reconstruct.
Nothing currently needs it. `dashy`'s `conf.yaml.j2` is a candidate if its
in-UI config editor (`data/conf.yml`) is ever used — see
[`adding-an-app.md`](adding-an-app.md#2-register-it-in-app_registry)
for the general rule.

## Syncing the LDAP observer account password

`tinyauth-ldap-observer-password` is generated and cached like any other
secret, but it's also consumed by the `lldap_bootstrap` role
(`deploy.yaml`'s Play 7), which sets it as the lldap `observer`
account's real password via lldap's own `bootstrap.sh` — see
[`lldap.md`](lldap.md#bootstrapping-the-observer-account). See
[`secrets-rotation.md`](secrets-rotation.md) for rotating it.
