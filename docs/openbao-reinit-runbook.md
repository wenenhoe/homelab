# OpenBao re-init runbook

For when OpenBao's raft dataset needs to be discarded and rebuilt from
scratch - not the [restore drill](openbao-backup-restore.md), which
deliberately preserves the original cluster's keys and data. See
[`openbao-vault-bootstrap.md`](openbao-vault-bootstrap.md) for what
the AppRole this runbook creates in step 4 actually is and how it's
used afterward; this doc is just the one-time procedure.

See [ADR 0027](decisions/0027-openbao-reinit-with-standing-vault-bootstrap-role.md)
for why this was necessary the first time. It shouldn't be needed
again for *that* reason - once `vault-bootstrap` exists, regaining
root is a policy edit away (see `openbao-vault-bootstrap.md`'s
emergency-root section), not another re-init. What's left here is
narrower: genuine raft-data loss or corruption a snapshot restore
can't fix.

1. **Full backup first:**
   `python3 -m cloud_credentials.dump_vault_to_file_cache` - never skip
   this; it's the only copy of everything once step 2 runs.
2. On `security`: stop the `openbao` container, remove the
   `openbao_data` volume's contents, restart it, then init fresh
   (commands mirrored from [`openbao.md`](openbao.md)'s **First init**
   section - that doc is canonical for the reasoning and for the exact
   command if the two ever disagree):

   ```sh
   docker exec -it openbao bao operator init -key-shares=3 -key-threshold=2
   ```

   Copy the 3 unseal shares and root token into the password manager
   entry plus one offline physical copy, same as the original bundle -
   this one fully supersedes it, replace rather than keep both.
   Unseal with 2 of the 3 shares
   (`docker exec -it openbao bao operator unseal`, once per share).

3. Recreate `controller`'s AppRole (commands mirrored from
   [`openbao-auth.md`](openbao-auth.md)'s Runbook section - canonical
   for TTL/parameter reasoning and the exact values if the two ever
   disagree):

   ```sh
   ssh security
   export BAO_TOKEN=<fresh root token from step 2>
   alias bao='docker exec -i -e BAO_TOKEN -e BAO_SKIP_VERIFY=true openbao bao'

   bao secrets enable -path=secret kv-v2
   bao auth enable approle

   # from controller, first: scp docker/openbao/policies/controller.hcl security:/tmp/
   docker exec -i -e BAO_TOKEN -e BAO_SKIP_VERIFY=true openbao \
     bao policy write controller - < /tmp/controller.hcl

   bao write auth/approle/role/controller \
     token_policies="controller" \
     token_ttl=1h \
     token_max_ttl=1h \
     secret_id_ttl=2160h \
     secret_id_num_uses=0

   bao read auth/approle/role/controller/role-id
   bao write -f auth/approle/role/controller/secret-id
   ```

   Copy the resulting `role_id`/`secret_id` into
   `ansible/files/secrets/openbao-controller-{role,secret}-id` on
   `controller`, `chmod 600` both - then confirm the AppRole actually
   works per `openbao-auth.md` step 6 before moving on, same reasoning
   as this runbook's own scope-proof in step 4 below.

4. Create `vault-bootstrap`, using the fresh root token from step 2 -
   nothing else can create it yet:

   ```sh
   ssh security
   export BAO_TOKEN=<fresh root token from step 2>
   alias bao='docker exec -i -e BAO_TOKEN -e BAO_SKIP_VERIFY=true openbao bao'

   # from controller, first: scp docker/openbao/policies/vault-bootstrap.hcl security:/tmp/
   docker exec -i -e BAO_TOKEN -e BAO_SKIP_VERIFY=true openbao \
     bao policy write vault-bootstrap - < /tmp/vault-bootstrap.hcl

   bao write auth/approle/role/vault-bootstrap \
     token_policies="vault-bootstrap" \
     token_ttl=1h \
     token_max_ttl=1h \
     secret_id_ttl=0 \
     secret_id_num_uses=0

   bao read auth/approle/role/vault-bootstrap/role-id
   bao write -f auth/approle/role/vault-bootstrap/secret-id
   ```

   `secret_id_ttl=0` (never expires) - this is a break-glass credential
   like the Shamir shares, not a rotation-habit one. Store the
   resulting `role_id`/`secret_id` the same way: password manager plus
   one offline physical copy, same entry class as the Shamir shares -
   never `ansible/files/secrets/`.

   **Confirm the scope actually holds before trusting it**, same
   reasoning as `openbao-auth.md`'s own step 6 - a policy file is a
   claim until proven. From `controller`, first:
   `scp docker/openbao/scripts/bao-login.sh security:/tmp/` (used here
   and again in step 7 - copy it once):

   ```sh
   BAO_TOKEN=$(/tmp/bao-login.sh "<role_id from above>")
   export BAO_TOKEN
   bao policy write _stage-test-policy - <<< 'path "sys/health" { capabilities = ["read"] }'   # succeeds
   bao kv get -mount=secret hosts/security/lldap-jwt-secret                                    # denied
   unset BAO_TOKEN
   ```

   The denied read is the actual proof: `vault-bootstrap` can write
   policy but genuinely cannot read a secret through any path of its
   own. Clean up the test policy with the root token, back on
   `security`: `bao policy delete _stage-test-policy`.
5. `python3 restore_hosts_scope_from_backup.py <backup-dir>` -
   **before** any `ansible-playbook deploy.yaml` run against the fresh
   Vault. Skipping this means the next `deploy.yaml` silently mints new
   random values for every `hex`/`uuid4` secret in the registry
   (ADR 0027's Context explains why). Since Track A stage 6 gave every
   `cloudflare-r2-*`/`backblaze-b2-*`/`oci-*` registry entry its own
   `vault_scope` (`cloud_credentials/leaf`), this one step now also
   restores all 20 of those - not just the `hosts/*` ones.
6. `python3 restore_cloud_credentials_from_backup.py <backup-dir>` -
   restores what step 5 can't reach: cloud_credentials' internal
   leaf/rotation bookkeeping keys with no `secrets_registry.yaml` entry
   of their own (`_rotation-key-*`, `_oci-leaf-user-ocid-*`, the two
   `oci-{write,read}-scim-id` values). The `_oci-leaf-user-ocid-*`
   duplicate under `cloud_credentials/leaf/` (see ADR 0027's Context) is
   not recreated - this script, like the retired
   `migrate_legacy_cache_to_vault.py` before it, only ever writes to
   each key's own registered category.
7. Provision the R2 watcher's AppRole (ADR 0026) using
   `vault-bootstrap`:

   ```sh
   ssh security
   BAO_TOKEN=$(/tmp/bao-login.sh "<vault-bootstrap role_id>")
   export BAO_TOKEN
   alias bao='docker exec -i -e BAO_TOKEN -e BAO_SKIP_VERIFY=true openbao bao'

   # from controller, copy the checked-in policy over first:
   #   scp docker/openbao/policies/r2-read-watcher.hcl security:/tmp/
   docker exec -i -e BAO_TOKEN -e BAO_SKIP_VERIFY=true openbao \
     bao policy write r2-read-watcher - < /tmp/r2-read-watcher.hcl

   bao write auth/approle/role/r2-read-watcher \
     token_policies="r2-read-watcher" \
     token_ttl=1h \
     token_max_ttl=1h \
     secret_id_ttl=0 \
     secret_id_num_uses=0

   bao read auth/approle/role/r2-read-watcher/role-id
   bao write -f auth/approle/role/r2-read-watcher/secret-id
   ```

   `secret_id_ttl=0` (never expires), unlike `controller`'s 90-day
   cycle: this identity lives permanently on `security` itself, not on
   a laptop with a rotation habit - same "always-on box" reasoning
   [ADR 0022](decisions/0022-approle-policy-structure-two-eras.md)
   gives for `cd_agent`'s own AppRoles, applied here a stage early
   since this identity exists before `cd_agent` does.

   No `secret_id_bound_cidrs`/`token_bound_cidrs` set here - unlike
   `cd_agent`'s genuine cross-host LAN traffic, the watcher and OpenBao
   both run on `security`, and whether that traffic presents as
   `127.0.0.1` or `security`'s LAN IP to OpenBao's listener isn't
   confirmed. Worth checking once the watcher's actual connection
   method is built, not guessed here - add the bind then if it's
   meaningful.

   Where the watcher's own `role_id`/`secret_id` get cached is part of
   building the watcher's systemd unit itself (not done yet - this
   step only provisions the identity it will use), matching
   `uptime_kuma_push`'s own env-file convention rather than
   `ansible/files/secrets/`.

8. Revoke root, same as `openbao-auth.md`'s own last step.
9. Confirm:

   ```sh
   python3 -m cloud_credentials.dump_vault_to_file_cache
   python3 -m cloud_credentials.diff_vault_backups \
     ~/secrets-backup-pre-reinit-<original-timestamp> \
     ~/secrets-backup-pre-reinit-<this-run's-timestamp>
   ```

   Expect `IDENTICAL`, no exceptions - the `leaf/`-side
   `_oci-leaf-user-ocid-*` duplicate from step 6 was never a second
   *file* in either dump (both always read from the correct
   `rotation/` path), so there's nothing that should legitimately
   differ here.

Every consumer of OpenBao is unusable for the duration - schedule this
when nothing else needs `check_freshness.py`, `snapshot-push.sh`, or a
`deploy.yaml` run to succeed.
