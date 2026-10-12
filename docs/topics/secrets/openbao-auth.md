# OpenBao Auth and Policies

Gives `controller` its own AppRole so day-to-day operation stops
depending on the initial root token. See
[ADR 0020 (Automation identity scope)](../../decisions/0020-automation-identity-and-access-scope/revision-000.md)
for the design this implements.

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
[`docker/openbao/policies/controller.hcl`](../../../docker/openbao/policies/controller.hcl) —
not under `docker/openbao/configs/`: that directory is seeded into
OpenBao's own config volume and auto-scanned at boot (see
[`openbao.md`](openbao.md)), and this is Vault ACL data applied via the
CLI after boot, not server config. Read/write on
`secret/data/hosts/*` and both
`secret/data/cloud_credentials/{leaf,rotation}/*`, plus read-only on
`sys/storage/raft/snapshot` (ADR 0020's Context explains the last one:
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
export BAO_ADDR=https://127.0.0.1:8200
export BAO_TLS_SERVER_NAME=openbao.{{ caddy_domain }}
export BAO_CACERT=/etc/step-ca/root_ca.crt
```

Native `bao` (`ansible/roles/openbao_cli`), real TLS against step-ca's
root cert; [`openbao.md`](openbao.md) covers init and unseal, the one
place that doesn't use it. `-tls-server-name` is required:
the leaf cert has no IP SAN, so dialing `127.0.0.1` needs the real SAN
supplied explicitly (see
[ADR 0034 (Operator bao CLI access)](../../decisions/0034-operator-access-to-the-openbao-cli/revision-000.md#context)).

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
   stable address to bind to (ADR 0020). Parameter choices:

   - `token_ttl`/`token_max_ttl` **1h, non-renewable.** Long enough for
     a full `deploy.yaml` run; short enough that a token leaked from
     one run doesn't outlive it by much. If a run genuinely needs
     longer, re-authenticate rather than renew — simpler than adding
     a renewal path to a role deleted outright once
     [its retirement](../../projects/cd-agent-controller-approle-retirement.md) lands.
   - `secret_id_ttl` **2160h (90 days), `secret_id_num_uses=0`
     (unlimited within that window).** Matches this repo's existing
     90-day rotation cadence for every other leaf/rotation credential
     ([ADR 0015 (Cloud credential expiry)](../../decisions/0015-cloud-credential-expiry/revision-000.md)),
     rather than cd_agent's never-expire shape — that shape is
     justified for an always-on box logging in every 2 minutes
     (0022); `controller` is a laptop with no fixed cadence, and
     [re-issuing the secret ID](#re-issuing-the-secret-id) by hand every
     quarter costs nothing extra over the credential rotation this repo
     already does by habit.
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
   from `security`'s own root-token session.** A login against
   `security`'s loopback address only proves the policy/role config is
   right; it doesn't prove `controller` can reach Vault's API at all,
   which the secrets role migration (`ensure_secret.yaml`
   reading/writing Vault) depends on. From `controller`, using the
   `role_id` cached in step 5 (paste `secret_id` from
   `ansible/files/secrets/openbao-controller-secret-id` when prompted —
   `bao_session.py` never takes it as an argument):

   ```sh
   cd tools && python3 -m openbao_utils.bao_session "$(cat ../ansible/files/secrets/openbao-controller-role-id)"
   ```

   This logs in over real TLS (`controller` always fetches step-ca's
   root cert fresh over SSH, since there's no local `step-ca`
   container to borrow from directly) and drops into an interactive
   shell with
   `BAO_ADDR`/`BAO_CACERT`/`BAO_TLS_SERVER_NAME`/`BAO_TOKEN` already
   exported — every native `bao` subcommand below runs unmodified
   inside it:

   ```sh
   bao kv put -mount=secret hosts/_approle-test probe=approle   # succeeds
   bao kv get -mount=secret hosts/_approle-test                # succeeds
   bao kv metadata delete -mount=secret hosts/_approle-test    # denied
   exit                                                       # revokes the token
   ```

   The last command is *supposed* to fail: `kv metadata delete` targets
   `secret/metadata/hosts/*`, and `controller`'s policy grants nothing
   there at all (only `create`/`read`/`update` on `secret/data/hosts/*`
   — no `delete`, on either path). A denied delete alongside a
   successful put/get is the actual proof this stage exists to
   produce, not a defect — `controller` can operate within its scope
   and provably cannot do the one thing 0022 never gave it. Exiting the
   shell revokes the token automatically — no `unset BAO_TOKEN` to
   remember.

   That does leave the leftover `_approle-test` key behind, since
   `controller`'s token can't remove it. Clean it up with the
   still-active root token instead, back on `security`:

   ```sh
   bao kv metadata delete -mount=secret hosts/_approle-test
   ```

7. **Revoke the root token** — safe once the AppRole is confirmed
   working end-to-end and `vault-bootstrap` exists
   ([`openbao-reinit-runbook.md`](openbao-reinit-runbook.md) step 4
   creates it): after the revoke it is the only way to write another
   policy or AppRole.

   ```sh
   bao token revoke -self
   ```

   From this point, the root token from `openbao.md`'s Init runbook no
   longer exists. Later admin access goes through `vault-bootstrap` in a
   `bao_session` ([`openbao-vault-bootstrap.md`](openbao-vault-bootstrap.md)),
   never a standing root credential.

## Re-issuing the secret ID

The cached `secret_id` stops working once its `secret_id_ttl` (90 days)
has passed; `stat -c %y ansible/files/secrets/openbao-controller-secret-id`
shows when the file was last written. The `role_id` doesn't change, so
only the `secret_id` file is replaced.

A failed login reports `invalid role or secret ID` for an expired
`secret_id`, an unknown `secret_id`, a `role_id` that no longer matches
and a missing role alike, so the first step below is what tells them
apart.

The root token from the runbook above no longer exists, so this goes
through the `vault-bootstrap` AppRole
([`openbao-vault-bootstrap.md`](openbao-vault-bootstrap.md)), from
`controller`. Its `secret_id` is typed at `bao_session`'s hidden prompt:

```sh
cd tools
printf 'vault-bootstrap role_id: '; read -r rid
python3 -m openbao_utils.bao_session "$rid"; unset rid
```

In the shell it spawns:

1. **Confirm the role is intact and the cached `role_id` still matches:**

   ```sh
   secrets=../ansible/files/secrets

   bao read auth/approle/role/controller
   [ "$(bao read -field=role_id auth/approle/role/controller/role-id)" = "$(cat "$secrets/openbao-controller-role-id")" ] \
     && echo "role_id MATCH" || echo "role_id MISMATCH"
   ```

   A missing role or a `role_id` mismatch means the AppRole was rebuilt,
   not that the `secret_id` expired; stop here and follow
   [`openbao-reinit-runbook.md`](openbao-reinit-runbook.md) step 3
   instead. `vault-bootstrap` cannot list a role's `secret_id`
   accessors, so a matching `role_id` plus a failing login is what
   points at the `secret_id`.

2. **Issue the new `secret_id` straight into the cache file**, so it is
   never shown on the terminal:

   ```sh
   umask 077
   new=$(bao write -f -field=secret_id auth/approle/role/controller/secret-id) \
     && [ -n "$new" ] \
     && printf '%s' "$new" > "$secrets/openbao-controller-secret-id" \
     && chmod 600 "$secrets/openbao-controller-secret-id" \
     && echo "secret_id written"
   unset new
   ```

   The file is only overwritten when `bao` succeeded.

3. **Confirm the pair logs in, then leave the session:**

   ```sh
   t=$(bao write -field=token auth/approle/login \
         role_id=@"$secrets/openbao-controller-role-id" \
         secret_id=@"$secrets/openbao-controller-secret-id") \
     && echo "controller login OK" && BAO_TOKEN="$t" bao token revoke -self
   unset t

   exit
   ```

   A login response's client token is the `token` field, the same form
   `snapshot-push.sh` logs in with; `-field=client_token` finds nothing.
   `exit` revokes the `vault-bootstrap` token.

## What this doesn't cover yet

`snapshot-push.sh` logs in as this AppRole itself (the `role_id` as an
argument, the `secret_id` at a hidden prompt) and is run by hand; see
[`openbao-backup-restore.md`](openbao-backup-restore.md).

`ensure_secret.yaml` is what reads
`openbao-controller-role-id`/`-secret-id` from Ansible's own secrets
cache.
