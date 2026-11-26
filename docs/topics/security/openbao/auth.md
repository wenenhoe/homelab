# OpenBao Auth and Policies

Gives `controller` its own AppRole so day-to-day operation stops
depending on the initial root token. See
[ADR 0020 (Automation identity scope)](../../../decisions/0020-automation-identity-and-access-scope/revision-000.md)
for the design this implements.

## Why a runbook, not an Ansible role

Every command below needs the root token — the only credential that
exists in a freshly-initialized Vault — as input.
[`deployment.md`](deployment.md)'s Init runbook already established why that
token must never touch a file on `security` or `controller`, or flow
through Ansible's own result-capture/`--diff` machinery (`no_log:`
suppresses *output*, not the token *input* an `environment:` var would
still need to come from somewhere — a new `vars_prompt`, which
[`secrets.md`](../secrets.md) already rules out for this repo). Same
reasoning as init/unseal: SSH to `security` directly and run these by
hand.

## The policy

Checked in at
[`docker/openbao/policies/controller.hcl`](../../../../docker/openbao/policies/controller.hcl) —
not under `docker/openbao/configs/`: that directory is seeded into
OpenBao's own config volume and auto-scanned at boot (see
[`deployment.md`](deployment.md)), and this is Vault ACL data applied via the
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
deliberately has no `caddy:` route (`deployment.md`). Run
`ansible-playbook playbooks/deploy.yaml --tags infra` (re-renders/reloads DNS
zone data only, no images touched) before testing a login from any
host other than `security` itself — the runbook below works without it
since it never leaves the `openbao` container's own network namespace.

## Runbook

```sh
# [1/4] controller: paste alone; it opens a shell on security and waits
ssh security
```

```sh
# [2/4] inside that shell: paste alone; it waits for the current root token (break-glass password-manager entry), hidden
read -rsp 'root token: ' BAO_TOKEN; echo; export BAO_TOKEN
```

```sh
# [3/4] same shell: paste alone; it waits for security's caddy_domain
read -r -p 'caddy_domain of security: ' caddy_domain
```

```sh
# [4/4] same shell
export BAO_ADDR=https://127.0.0.1:8200
export BAO_TLS_SERVER_NAME="openbao.$caddy_domain"
export BAO_CACERT=/etc/step-ca/root_ca.crt
```

Native `bao` (`ansible/roles/openbao_cli`), real TLS against step-ca's
root cert; [`deployment.md`](deployment.md) covers init and unseal, the one
place that doesn't use it. `-tls-server-name` is required:
the leaf cert has no IP SAN, so dialing `127.0.0.1` needs the real SAN
supplied explicitly (see
[ADR 0106 (Operator bao CLI access)](../../../decisions/0106-operator-access-to-the-openbao-cli/revision-000.md#context)).

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

   No `secret_id_bound_cidrs`/`token_bound_cidrs`: `controller` has no
   stable address to bind to (ADR 0020).

   | Parameters | Why |
   | :--- | :--- |
   | `token_ttl`, `token_max_ttl` (non-renewable) | Covers a full `deploy.yaml` run without a leaked token outliving it by much. A run that needs longer logs in again; no renewal path is added to a role that [its retirement](../../../projects/cd-agent-controller-approle-retirement.md) deletes. |
   | `secret_id_ttl` | The same rotation cadence as every leaf and rotation credential ([ADR 0109 (Cloud credential expiry)](../../../decisions/0109-knowing-a-cloud-credential-is-about-to-expire/revision-000.md)). `cd_agent`'s never-expiring shape suits an always-on host, not a laptop; [re-issuing](#re-issuing-the-secret-id) by hand joins a routine already kept. |
   | `secret_id_num_uses=0` (unlimited) | The number of `ansible-playbook` runs in that window can't be predicted. |

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
   # controller, from the repo root: paste alone; it waits for the role_id, then the secret_id, hidden
   read -r -p 'controller role_id: ' role_id; read -rsp 'controller secret_id: ' secret_id; echo
   ```

   ```sh
   # same shell
   (
     umask 077
     printf '%s' "$role_id" > ansible/files/secrets/openbao-controller-role-id
     printf '%s' "$secret_id" > ansible/files/secrets/openbao-controller-secret-id
     chmod 600 ansible/files/secrets/openbao-controller-{role,secret}-id
   )
   unset role_id secret_id
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
   `shell.py` never takes it as an argument):

   ```sh
   cd tools && python3 -m openbao_utils.shell "$(cat ../ansible/files/secrets/openbao-controller-role-id)"
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
   ([`reinit-runbook.md`](reinit-runbook.md) step 4
   creates it): after the revoke it is the only way to write another
   policy or AppRole.

   ```sh
   bao token revoke -self
   ```

   From this point, the root token from `deployment.md`'s Init runbook no
   longer exists. Later admin access goes through `vault-bootstrap` in an
   `openbao_utils.shell` session ([`vault-bootstrap.md`](vault-bootstrap.md)),
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
([`vault-bootstrap.md`](vault-bootstrap.md)), from
`controller`. Its `secret_id` is typed at `openbao_utils.shell`'s hidden prompt:

```sh
cd tools
read -r -p 'vault-bootstrap role_id: ' rid && python3 -m openbao_utils.shell "$rid"; unset rid
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
   [`reinit-runbook.md`](reinit-runbook.md) step 3
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
argument, the `secret_id` from the cached file, else a hidden prompt) and is run by hand; see
[`backup-restore.md`](backup-restore.md).

`ensure_secret.yaml` is what reads
`openbao-controller-role-id`/`-secret-id` from Ansible's own secrets
cache.
