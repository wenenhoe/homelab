# Secrets

For the offsite-backup system specifically (SeaweedFS, GPG-encrypted
archives, restore) — including *why* the S3 credentials generated
here need a controller-side cache in the first place — see
[`disaster-recovery.md`](disaster-recovery.md).

Every value this repo needs but doesn't want hardcoded — whether Ansible
can generate it itself or not — is resolved once and cached on the
controller by a single, reusable mechanism: the `secrets` role
(`ansible/roles/secrets/`), driven by a central registry
(`ansible/inventory/group_vars/all/secrets_registry.yaml`). It runs in
`deploy.yaml`'s Play 1, tagged `always` (same reasoning as `compose`'s
`preinit.yaml`: every downstream config template that reads a secret
needs it to already exist, regardless of which `--tags` subset a given
run uses — confirmed live via `--list-tasks --tags images`, which shows
`Include secrets role` at the same `always`-tagged level as
`preinit.yaml`, before Play 4 ever reaches `compose_app`/config
rendering).

This replaced four different ad hoc patterns that used to be spread
across the codebase: `deploy.yaml`'s entire `vars_prompt` block (typed in
on every run, both truly external credentials like the DigitalOcean API
key and plain config like `main_domain`), inline `lookup('password', ...)`
calls with a hand-built lookup-term string (`seaweedfs_s3_access_key`/
`seaweedfs_s3_secret_key`), `lookup('pipe', 'openssl rand -hex 32')`/a
`uuid` one-liner baked directly into a template (`lldap`'s three secrets,
`shlink`'s API key), and a gitignored `-e @secrets.yaml` file for
non-interactive runs. All of it — including any *future* secret or
config value — now goes through the same path:

1. Add an entry to `secrets_registry.yaml`:
   ```yaml
   secrets_registry:
     my-new-thing: { format: hex, length: 32 }
   ```
2. Reference `secrets_generated['my-new-thing']` from a plain var in
   `group_vars/all/main.yaml` (so a template only ever sees an ordinary
   variable name, never the registry key or the mechanism behind it):
   ```yaml
   my_new_thing: "{{ secrets_generated['my-new-thing'] }}"
   ```
3. Use `{{ my_new_thing }}` in the app's `configs/*.j2` template, with
   `no_log: true` on its `app_registry` entry if the value is a real
   secret (not just a hostname or timezone) — see "`no_log: true`"
   below for why.

No template should ever call `lookup('password', ...)` or
`lookup('pipe', ...)` directly again, and `deploy.yaml` should never grow
a new `vars_prompt` entry — if a new secret or config value needs one of
those, it needs a registry entry instead.

## Three formats

- **`hex`** (most generated secrets) — a thin, parameterized wrapper
  around `lookup('password', <path> chars=hexdigits length=<n>)`.
  `password` already *is* the generate-once-and-cache mechanism: per
  Ansible's own docs, "If the file already exists, no data will be
  written to it. If the file has contents, those contents will be read
  in as the password" — and its write path creates any missing parent
  directory itself (confirmed against `ansible-core`'s `password` lookup
  source: both its locking and its write path call `makedirs_safe()`
  first). The role's job here is just building that lookup term
  correctly from the registry so no call site hand-rolls it, and
  enforcing the `chars=hexdigits`-as-**named-charset** convention below.
- **`uuid4`** (`shlink-api-key` only, deliberately kept as a real UUID4
  rather than collapsed into a hex token) — `password`'s `chars=` option
  can only draw from a character set, which can never produce a
  structurally valid UUID4 (fixed version/variant nibbles), so this
  format has real generate-once-and-cache task logic instead: stat the
  cache file, generate via `python3 -c "import uuid; print(uuid.uuid4())"`
  only if missing, cache it with `mode: "0600"`, then always read it back
  — mirroring what `password` does internally, for a format it doesn't
  support natively. See `ansible/roles/secrets/tasks/ensure_secret.yaml`.
- **`manual`** (every remaining `vars_prompt` value — externally-issued
  credentials like the DigitalOcean API key, plain config like
  `main_domain`, and the two Beszel values that genuinely don't exist
  until after the hub's first boot) — Ansible can't generate any of
  these, so there's no generation step at all: the cache file must
  already exist before this task runs. **Missing entirely → the play
  fails immediately**, printing the registry entry's `description` and
  the exact command to create the file, rather than silently deploying
  with a blank credential nobody noticed. **Present but empty is a valid
  value** (reads back as `""`), not an error — existence is what's
  checked, not content. This is what lets `beszel-hub-key`/
  `beszel-agent-token` start out blank without failing every run until
  you fill them in: both are marked `allow_blank: true` in the registry,
  which `bootstrap_secrets.py` (below) reads to know it's fine to write
  an empty placeholder for those two specifically, instead of demanding
  a value that can't exist yet.

`chars=hexdigits` is a named charset, never a literal alphabet string, in
every hex secret's definition — deliberate, so `gitleaks` doesn't flag a
literal hex-alphabet string sitting next to a `_secret`/`_key`/`_pass`-shaped
variable name. `secrets_registry.yaml` only ever stores `format: hex`
plus a `length`, never a literal charset, for the same reason.

## Bootstrapping manual secrets

`manual` entries can't be generated, so before your first `deploy.yaml`
run, populate them once:

```sh
python3 ansible/bootstrap_secrets.py
```

Walks every `manual` entry in `secrets_registry.yaml`, skips anything
whose cache file already exists, and for everything else prompts for a
value (masked input, via `getpass`, for anything marked `sensitive:
true` in the registry) — re-prompting until something non-empty is
given, except for `allow_blank: true` entries, where pressing Enter
writes an empty placeholder on purpose. Safe to re-run any time: it
never touches a file that already exists, so re-running only fills in
whatever's still missing (a new registry entry someone added, or a
Beszel value you left blank the first time). Prefer hand-creating the
file yourself (`printf '%s' '<value>' >
ansible/files/secrets/<registry-key> && chmod 600
ansible/files/secrets/<registry-key>`) if you're scripting this instead
— the script is a convenience, not the only way in.

Values that can't be typed in ahead of time (Beszel's key/token) still
need the manual redeploy sequence documented in
[`beszel.md`](beszel.md): deploy once with them blank, retrieve the real
values from the hub's web UI, write them to their cache files (by hand,
or via `bootstrap_secrets.py` re-run), redeploy.

## Where the cache lives

Every generated value — `hex` and `uuid4` alike — lands at
`ansible/files/secrets/<registry-key>` on the **controller** (not a
managed host), one file per secret, gitignored
(`ansible/files/secrets/`), never committed. Real target hosts only ever
see the rendered `.env`/config file the value ends up in (already
`no_log: true`/`mode: "0600"` where relevant), never the cache directory
itself.

`seaweedfs-s3-access-key`/`seaweedfs-s3-secret-key` keep their existing
on-disk filenames — this registry migration was deliberately **not** a
rename, to avoid orphaning any value a real controller had already
cached before this change landed. Every other secret is free to follow
the same kebab-case convention from a clean slate.

**Rotating a credential**: delete the relevant file under
`ansible/files/secrets/`, then redeploy every host that renders a config
depending on it — this actually propagates now (see "`no_log: true`"
below for why an earlier version of this doc had to hedge that
statement). For `seaweedfs-s3-*` specifically this means `storage`
(so `s3-identity.json` picks up the new value) and every host running
`backup_agent` (so their env files match again) — in either order, but
both are required, or SeaweedFS and its clients will disagree. Values
consumed by only one host (`lldap`'s three secrets, `shlink`'s API key)
just need that one host redeployed.

## Why S3 credentials specifically need a controller-side cache

`offen/docker-volume-backup`'s S3 client and SeaweedFS's own identity
config are independently rendered on **different hosts**
(`storage`'s `s3-identity.json` and every `backup_agent` instance's
`.env.*-group` files) — a raw one-off generator in each template (the
`lldap`/`shlink` style, back when they used one) would produce a
different value per host, and whichever host rendered first would
permanently disagree with the rest. Only a controller-side cache (what
this role does for every secret, not just these two) keeps every
independently-rendered consumer in sync. `lldap`'s secrets don't have
this problem — each is generated and consumed in one file on one host —
but they go through the same mechanism anyway now, for consistency and a
single tested code path rather than two.

## `no_log: true` — why a secret never appears in `--diff` output

Every `app_registry` entry whose `configs` render a real secret (an API
key, token, or password — not just a hostname or timezone) sets
`no_log: true` on that config. This is the thing that actually matters
for secret-bearing configs, not `force`. Confirmed directly (not
assumed): a `template` task without `no_log` prints the full new
content to the console the moment it differs from what's already on the
target host — `ansible-playbook ... --diff` on a task rendering
`API_KEY=new-value` shows exactly that line, in plaintext, as a
`+` addition. `no_log: true` suppresses this completely, including on
task failure (Ansible replaces the entire result with `censored due to
'no_log: true'`), while a plain change still reports `changed: true` so
you can tell *that* something rendered without seeing *what*.

This risk exists on the **first** deploy too, not only a later
rotation — a file that doesn't exist yet is itself a "diff" (an
addition against nothing), so a secret-bearing config needs `no_log`
regardless of whether it's ever expected to change again.

**`force: false` is not the right tool for this**, and every
secret-bearing config in this registry has moved off it (see history —
it briefly followed the older `lookup('pipe', 'openssl rand -hex 32')`
templates' convention of relying on `force: false` for a completely
different reason: those had *no caching of their own*, so `force: false`
was the only thing stopping a fresh random value from being generated
on every single deploy. Now that idempotency lives in the controller-side
cache instead — see "Three formats" above — nothing left in this registry
actually needs `force: false`, and keeping it around would silently
defeat the "Rotating a credential" workflow above: `force: false` means
`ansible.builtin.template` leaves an existing destination file alone
**regardless of content**, so deleting the controller-side cache file and
redeploying would never actually propagate the new value to a host that
already has one rendered — a real gap an earlier version of this section
didn't call out clearly enough. Every current secret-bearing config
therefore just uses the module's own default (`force: true`, i.e.
"overwrite when content differs, leave alone when it doesn't" — normal
idempotent behavior) plus `no_log: true`.

## `force: false` — reserved for genuinely unreproducible state, nothing else

Every config in this registry defaults to `force: true` — this repo is
the source of truth, so a redeploy always overwrites a config that's
drifted from what its template would render, rather than leaving a
stale value in place indefinitely. `bind9`, `cobalt`, `kms`,
`seaweedfs`'s `env.j2`, `wetty`, and `minecraft` used to set
`force: false` too, despite none of them rendering a secret or holding
any state Ansible can't fully reconstruct from vars (a timezone, a
hostname, a domain) — audited by reading each template's actual
content, not assumed, and all six removed.

`force: false` earns its place only on a config whose destination can
hold real content Ansible has no way to reconstruct — something the
*app itself* writes back to the same file after Ansible first renders
it, where overwriting on every deploy would silently destroy something
no template could regenerate. Nothing in this registry currently needs
it. `dashy`'s `conf.yaml.j2` is an open question, not yet decided
either way: Dashy ships an in-UI config editor that saves back to
`data/conf.yml`, and nothing in this repo's compose file disables it.
If that editor is ever used, `force: true` would silently overwrite
whatever was changed there on the next deploy. See the comment on
`dashy`'s `app_registry` entry.

## Syncing the LDAP observer account password

`tinyauth-ldap-observer-password` is a special case worth calling out
explicitly: generating and caching the value is only half the story.
Tinyauth binds to lldap as a read-only account named `observer`
(`docker/tinyauth/configs/config.yaml.j2`'s `ldap.bindDn`), and **nothing
in this codebase creates that account or sets its password** — traced
through `docker/lldap/scripts/` and the rest of the repo, and confirmed
there's no scripted path today. lldap's own docs describe this as a
web-UI operation: create the user, add it to a read-only group
(`lldap_strict_readonly`/`lldap_readonly` depending on your lldap
version — check your deployed version's admin UI), and set its password
by hand.

**After (re)generating this secret, the operator must manually set the
`observer` account's password in lldap's admin web UI to the same
value**, or tinyauth's LDAP bind will fail with invalid credentials. Read
the cached value with:

```sh
cat ansible/files/secrets/tinyauth-ldap-observer-password
```

This was already true before this migration (the operator previously
typed this password into `vars_prompt` and then had to separately create
the matching lldap account) — the migration doesn't add a new manual
step, it just moves the value from "typed in on every run" to "generated
once and cached," which is why this note exists here rather than being
a new gap introduced by the change.
