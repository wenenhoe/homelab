# OpenBao Auth and Policies (Track A Stage 3)

Gives `controller` its own AppRole so day-to-day operation stops
depending on the initial root token. See
[ADR 0022](decisions/0022-approle-policy-structure-two-eras.md) for the
design this implements, and
[`openbao-migration-roadmap.md`](openbao-migration-roadmap.md) for
where this sits in the overall migration.

## Why a runbook, not an Ansible role

Every command below needs the root token — the only credential that
exists in a freshly-initialized Vault — as input.
[`openbao.md`](openbao.md)'s Init runbook already established why that
token must never touch a file on `security` or `controller`, or flow
through Ansible's own result-capture/`--diff` machinery (`no_log:`
suppresses *output*, not the token *input* an `environment:` var would
still need to come from somewhere — a new `vars_prompt`, which
[`secrets.md`](secrets.md) already rules out for this repo). Same
reasoning as init/unseal: SSH to `security` directly and run these by
hand.

## The policy

Checked in at
[`docker/openbao/policies/controller.hcl`](../docker/openbao/policies/controller.hcl) —
not under `docker/openbao/configs/`: that directory is seeded into
OpenBao's own config volume and auto-scanned at boot (see
[`openbao.md`](openbao.md)), and this is Vault ACL data applied via the
CLI after boot, not server config. Read/write on
`secret/data/hosts/*` and both
`secret/data/cloud_credentials/{leaf,rotation}/*`, plus read-only on
`sys/storage/raft/snapshot` (ADR 0022's Context explains the last one:
it lets `snapshot-push.sh` eventually authenticate as this role
instead of a human-exported root token).

## Prerequisite: OpenBao's hostname must actually resolve

`openbao.{{ caddy_domain }}` (the SAN on its cert) has no DNS record
until `host_vars/security.yaml`'s hand-written `extra_records` CNAME
for it is deployed — bind9 doesn't auto-generate one, since OpenBao
deliberately has no `caddy:` route (`openbao.md`). Run
`ansible-playbook deploy.yaml --tags infra` (re-renders/reloads DNS
zone data only, no images touched) before testing a login from any
host other than `security` itself — the runbook below works without it
since it never leaves the `openbao` container's own network namespace.

## Runbook

```sh
ssh security
export BAO_TOKEN=<current root token, from the break-glass password-manager entry>
alias bao='docker exec -e BAO_TOKEN -e BAO_SKIP_VERIFY=true openbao bao'
```

No `-address=` flag needed: `compose.yaml.j2` sets no `BAO_ADDR`/
`VAULT_ADDR` in the container, and `bao`'s own default
(`https://127.0.0.1:8200`) is already correct here — same reason
`openbao.md`'s init/unseal commands never pass it either. If a command
ever does need it, OpenBao's CLI parses per-command flags *after* the
subcommand, not before (`bao <command> [options] [path] [args]`,
confirmed against [openbao.org's own CLI docs](https://openbao.org/docs/commands)) —
so it goes on the individual command, never baked into this alias.

1. **Enable the KV v2 engine**, if not already present (`bao secrets
   list` shows nothing at `secret/` on a fresh Vault):

   ```sh
   bao secrets enable -path=secret kv-v2
   ```

2. **Enable the AppRole auth method:**

   ```sh
   bao auth enable approle
   ```

3. **Write the policy**, from the checked-in file (copy it to `security`
   first, e.g. `scp docker/openbao/policies/controller.hcl
   security:/tmp/`):

   ```sh
   docker exec -i -e BAO_TOKEN -e BAO_SKIP_VERIFY=true openbao \
     bao policy write controller - < /tmp/controller.hcl
   ```

4. **Create the `controller` role:**

   ```sh
   bao write auth/approle/role/controller \
     token_policies="controller" \
     token_ttl=1h \
     token_max_ttl=1h \
     secret_id_ttl=2160h \
     secret_id_num_uses=0
   ```

   No `secret_id_bound_cidrs`/`token_bound_cidrs` — `controller` has no
   stable address to bind to (ADR 0022). Parameter choices, since 0022
   leaves Era A's own values as a build question:

   - `token_ttl`/`token_max_ttl` **1h, non-renewable.** Long enough for
     a full `deploy.yaml` run; short enough that a token leaked from
     one run doesn't outlive it by much. If a run genuinely needs
     longer, re-authenticate rather than renew — simpler than adding
     a renewal path to a role this era deletes outright once Track B
     lands.
   - `secret_id_ttl` **2160h (90 days), `secret_id_num_uses=0`
     (unlimited within that window).** Matches this repo's existing
     90-day rotation cadence for every other leaf/rotation credential
     ([ADR 0015](decisions/0015-credential-expiry-native-where-possible-self-tracked-where-not.md)),
     rather than cd_agent's never-expire shape — that shape is
     justified for an always-on box logging in every 2 minutes
     (0022); `controller` is a laptop with no fixed cadence, and
     re-running this runbook by hand every quarter costs nothing extra
     over the credential rotation this repo already does by habit.
     `secret_id_num_uses` isn't capped separately, since the number of
     `ansible-playbook` runs in 90 days isn't something to predict or
     constrain.

5. **Generate `role_id` and `secret_id`:**

   ```sh
   bao read auth/approle/role/controller/role-id
   bao write -f auth/approle/role/controller/secret-id
   ```

   Copy `role_id` into `ansible/files/secrets/openbao-controller-role-id`
   and `secret_id` into `ansible/files/secrets/openbao-controller-secret-id`
   on `controller` (not on `security` — `role_id` isn't sensitive, but
   keep both files together for consistency), `chmod 600` both:

   ```sh
   printf '%s' '<role_id>'   > ansible/files/secrets/openbao-controller-role-id
   printf '%s' '<secret_id>' > ansible/files/secrets/openbao-controller-secret-id
   chmod 600 ansible/files/secrets/openbao-controller-{role,secret}-id
   ```

   Same offline discipline as every other credential in this repo:
   never in shell scrollback longer than it takes to paste, never
   committed (`ansible/files/secrets/` is gitignored).

6. **Confirm the AppRole actually works — from `controller`, not just
   from inside the `openbao` container.** A login from `security` via
   `docker exec` only proves the policy/role config is right; it
   doesn't prove `controller` can reach Vault's API at all, which is
   the thing this stage exists to unblock for stage 4. From
   `controller`, using the `role_id`/`secret_id` files cached in step
   5 (confirmed working over the real network, using `docker run
   --entrypoint bao` there rather than a locally-installed binary):

   ```sh
   bao write auth/approle/login \
     role_id="$(cat ansible/files/secrets/openbao-controller-role-id)" \
     secret_id="$(cat ansible/files/secrets/openbao-controller-secret-id)"
   export BAO_TOKEN=<the "token" value from that output>
   bao kv put -mount=secret hosts/_stage3-test probe=stage3   # succeeds
   bao kv get -mount=secret hosts/_stage3-test                # succeeds
   bao kv metadata delete -mount=secret hosts/_stage3-test    # denied
   unset BAO_TOKEN
   ```

   The last command is *supposed* to fail: `kv metadata delete` targets
   `secret/metadata/hosts/*`, and `controller`'s policy grants nothing
   there at all (only `create`/`read`/`update` on `secret/data/hosts/*`
   — no `delete`, on either path). A denied delete alongside a
   successful put/get is the actual proof this stage exists to
   produce, not a defect — `controller` can operate within its scope
   and provably cannot do the one thing 0022 never gave it.

   That does leave the leftover `_stage3-test` key behind, since
   `controller`'s token can't remove it. Clean it up with the
   still-active root token instead, back on `security`:

   ```sh
   bao kv metadata delete -mount=secret hosts/_stage3-test
   ```

7. **Revoke the root token** — safe now that the AppRole is confirmed
   working end-to-end:

   ```sh
   bao token revoke -self
   ```

   From this point, the root token from `openbao.md`'s Init runbook no
   longer exists. Any future admin/debug access mints a fresh,
   narrowly-scoped, short-lived token the same way stage 2's restore
   drill already does — never a standing root credential.

## What this doesn't cover yet

`snapshot-push.sh` still requires a human to export `BAO_TOKEN` by
hand — see [`openbao-backup-restore.md`](openbao-backup-restore.md)'s
"Open follow-ups". The policy above grants the capability; wiring the
script to actually log in via this AppRole is separate, deliberately
deferred work (that doc explains why).

Track A stage 4 (migrating `ensure_secret.yaml` to Vault) is the first
thing that reads `openbao-controller-role-id`/`-secret-id` from
Ansible's own secrets cache.
