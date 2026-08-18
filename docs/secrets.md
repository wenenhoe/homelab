# Secrets

For the offsite-backup S3 credentials specifically, see
[`disaster-recovery.md`](disaster-recovery.md).

Every value this repo needs but doesn't want hardcoded is resolved once
and cached on the controller by the `secrets` role
(`ansible/roles/secrets/`), driven by a central registry
(`ansible/inventory/group_vars/all/secrets_registry.yaml`). It runs as
`deploy.yaml`'s Play 0, tagged `always`, `gather_facts: false` — before
Play 1, since `ansible_host` itself resolves through a secret
(`main_domain`) and Play 1's implicit fact-gathering needs a live
connection first.

No template should call `lookup('password', ...)` / `lookup('pipe', ...)`
directly, and `deploy.yaml` should never grow a new `vars_prompt` entry —
any new secret or config value goes through the registry instead:

1. Add an entry to `secrets_registry.yaml`:
   ```yaml
   secrets_registry:
     my-new-thing: { format: hex, length: 32 }
   ```
2. Reference it from a plain var in `group_vars/all/main.yaml`:
   ```yaml
   my_new_thing: "{{ secrets_generated['my-new-thing'] }}"
   ```
3. Use `{{ my_new_thing }}` in the app's `configs/*.j2` template, with
   `no_log: true` on its `app_registry` entry if it's a real secret (see
   `no_log: true` below).

## Three formats

- **`hex`** (most secrets) — wraps `lookup('password', <path>
  chars=hexdigits length=<n>)`; `password` itself generates once and
  caches to a file. `chars=hexdigits` must be the named charset, never a
  literal alphabet string, so `gitleaks` doesn't flag it next to a
  `_secret`/`_key`-shaped var name.
- **`uuid4`** (`shlink-api-key` only) — `password`'s `chars=` can't
  produce a structurally valid UUID4, so this format generates via
  `python3 -c "import uuid; print(uuid.uuid4())"` on first use and caches
  it with `mode: "0600"`. See `ansible/roles/secrets/tasks/ensure_secret.yaml`.
- **`manual`** (externally-issued credentials and plain config Ansible
  can't generate, e.g. the DigitalOcean API key, `main_domain`, Beszel's
  post-boot key/token) — no generation step; the cache file must already
  exist. Missing → the play fails immediately with the registry entry's
  `description` and the command to create the file. Present-but-empty is
  valid (not an error) for entries marked `allow_blank: true`, which lets
  Beszel's two values start blank.

## Bootstrapping manual secrets

Before your first `deploy.yaml` run:

```sh
python3 ansible/bootstrap_secrets.py
```

Prompts for every `manual` entry that isn't already cached (masked input
for anything marked `sensitive: true`), skipping entries that already
have a cache file. Safe to re-run. To set a value without the script:

```sh
printf '%s' '<value>' > ansible/files/secrets/<registry-key>
chmod 600 ansible/files/secrets/<registry-key>
```

Beszel's key/token can't be known ahead of time — see the manual
redeploy sequence in [`beszel.md`](beszel.md).

## Where the cache lives

`ansible/files/secrets/<registry-key>` on the controller, one file per
secret, gitignored, never committed. Target hosts only ever receive the
rendered config the value ends up in.

**Rotating a credential**: delete the file under `ansible/files/secrets/`,
then redeploy every host that renders a config depending on it. Since the
per-host SeaweedFS identity redesign
([`disaster-recovery.md`](disaster-recovery.md)), each `seaweedfs-s3-*-key-<host>`
is independent — rotating `services`' key only needs `storage` (identity
config) and `services` redeployed, not `security`/`play` too (either
order, but both are required or the S3 client and server will disagree).
`seaweedfs-s3-*-key-admin` (bucket creation only) only needs `storage`.
Single-host secrets (`lldap`'s three, `shlink`'s API key) just need that
host redeployed.

## Why S3 credentials need a controller-side cache

`docker-volume-backup`'s S3 client (`backup_agent` hosts) and SeaweedFS's
own identity config (`storage`) are rendered independently on different
hosts. Without a shared cache, each would generate its own value and
permanently disagree. Every secret goes through the same cache for
consistency, even ones like `lldap`'s that are only ever rendered on one
host.

## `no_log: true`

Every `app_registry` entry whose `configs` render a real secret (API key,
token, password — not a hostname or timezone) sets `no_log: true`. Without
it, `ansible-playbook --diff` prints the new value in plaintext on any
task where content changes — including the first deploy, since a
not-yet-existing file still counts as a diff. `no_log: true` suppresses
this (including on task failure) while still reporting `changed: true`.

## `force: false`

Every config in this registry defaults to `force: true` (overwrite on
drift) — this repo is the source of truth. Reserve `force: false` for a
destination the *app itself* writes back to after Ansible first renders
it, where overwriting would destroy state no template can reconstruct.
Nothing currently needs it. `dashy`'s `conf.yaml.j2` is a candidate if its
in-UI config editor (`data/conf.yml`) is ever used — see the comment on
`dashy`'s `app_registry` entry.

## Syncing the LDAP observer account password

`tinyauth-ldap-observer-password` is generated and cached like any other
secret, but it's also consumed by the `lldap_bootstrap` role
(`deploy.yaml`'s Play 7), which sets it as the lldap `observer`
account's real password via lldap's own `bootstrap.sh` — see
[`lldap.md`](lldap.md#bootstrapping-the-observer-account). Rotating it
is the same as any other secret (see "Rotating a credential" above):
delete the cache file and redeploy `security` — Play 7 updates the
existing account in place, no manual web-UI step required.
