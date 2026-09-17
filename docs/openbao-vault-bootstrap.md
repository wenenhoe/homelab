# OpenBao's `vault-bootstrap` AppRole

The standing answer to "how does this repo create a new Vault
policy/AppRole, now that the initial root token is revoked." See
[ADR 0025](decisions/0025-openbao-reinit-with-standing-vault-bootstrap-role.md)
for why this exists instead of a permanent root token or a repeat
re-init every time a new identity is needed.

## What it can and can't do

Policy: [`vault-bootstrap.hcl`](../docker/openbao/policies/vault-bootstrap.hcl) -
`create`/`update` on `sys/policies/acl/*` and `auth/approle/role/*`
only. It cannot read a single application secret (`secret/data/*` is
untouched by its policy), cannot seal/unseal, cannot enable a secrets
engine or auth method, cannot touch `sys/raw`, and does not hold
`sudo` on `sys/generate-root-token/*` as a standing grant.

That said, policy-write is inherently self-escalating in Vault/OpenBao
ACLs - a token that can write policy can always author itself a wider
one. `vault-bootstrap` doesn't eliminate that; it turns "instant
god-mode" into a two-step, audit-logged action (the audit device from
[ADR 0026](decisions/0026-openbao-audit-device-and-r2-per-read-watcher.md)
is live, so a policy edit followed by a login is visible, not silent).
Treat its `secret_id` with the same offline discipline as the Shamir
shares - never a casual `ansible/files/secrets/` entry - since it is,
functionally, this repo's root-recovery mechanism now.

## Day-to-day use: minting a new AppRole

```sh
cd tools && python3 -m openbao_utils.bao_session <vault-bootstrap role_id>
```

Paste `secret_id` when prompted (from the password manager — see
"What it can and can't do" above, never `ansible/files/secrets/`).
Runs from `controller`, fetching step-ca's root cert fresh over SSH
each time (`bao_session.py`'s own docstring). Drops into an
interactive shell with `BAO_ADDR`/`BAO_CACERT`/
`BAO_TLS_SERVER_NAME`/`BAO_TOKEN` already exported — every command
below is plain native `bao`:

```sh
bao policy write <new-role-name> - < /tmp/<new-role-name>.hcl
bao write auth/approle/role/<new-role-name> \
  token_policies="<new-role-name>" \
  token_ttl=<...> token_max_ttl=<...> \
  secret_id_ttl=<...> secret_id_num_uses=<...>
bao read auth/approle/role/<new-role-name>/role-id
bao write -f auth/approle/role/<new-role-name>/secret-id
exit   # revokes the vault-bootstrap token
```

Same parameter-choice discipline as `openbao-auth.md`'s `controller`
role: pick TTLs/CIDR-binds appropriate to the new identity's own job,
don't copy `controller`'s or `vault-bootstrap`'s own values by default.

## Using this for emergency root access

If a genuine need for full root access ever comes up (not just another
narrow AppRole), `vault-bootstrap` can produce one without a second
re-init - the same self-escalation property above, deliberately used
on purpose this one time:

1. Log in with `vault-bootstrap`
   (`cd tools && python3 -m openbao_utils.bao_session <vault-bootstrap role_id>`) —
   the spawned shell is already fully interactive, so step 4's
   unseal-key submission below needs no special handling the way a
   `docker exec -it` alias once did.
2. `bao policy write vault-bootstrap-emergency -`: a copy of
   `vault-bootstrap.hcl` plus one added stanza:
   `path "sys/generate-root-token/*" { capabilities = ["sudo", "create", "read", "update", "delete"] }`.
   `read` and `delete` are both required, not just `sudo`/`create`/
   `update` — `-generate-otp`'s status check and `-cancel` 403 without
   them, confirmed live.
3. `bao write auth/approle/role/vault-bootstrap token_policies="vault-bootstrap-emergency"`,
   then exit and log in again
   (same `bao_session.py` command as step 1) — a token's policies are
   fixed at login time, so the updated role only takes effect on the
   next login. AppRole role writes on this backend merge into the
   stored role rather than replacing it — `pathRoleCreateUpdate` loads
   the existing role first and only overwrites fields present in the
   request (confirmed from `path_role.go`/`tokenutil.go`), so a field
   left off this command keeps its current stored value. Re-supplying
   every field anyway is still worth doing for an explicit audit
   trail, just not required to avoid data loss.
4. `bao operator generate-root -generate-otp`, then
   `bao operator generate-root -init -otp="<otp>"` — returns a
   `Nonce`. Submit each Shamir key with
   `bao operator generate-root -otp="<otp>" -nonce="<nonce>"`, repeated
   once per key up to the configured threshold (`-status` checks
   progress without consuming a key). The final submission returns an
   `Encoded Token`; decode it with
   `bao operator generate-root -decode="<encoded>" -otp="<otp>"` for
   the actual root token. Confirmed against this CLI's own `-h` output
   and a live run.
5. Use the root token for whatever the actual emergency need is.
6. Revert — three things, not one:
   - Rebind `vault-bootstrap` back to `token_policies="vault-bootstrap"`.
   - `bao policy delete vault-bootstrap-emergency` — deleting the
     role's reference to it isn't enough; the policy object itself
     stays unless removed, sitting unattached and unused, which is
     exactly the kind of "slower-to-notice god-mode" this design
     exists to avoid.
   - `bao token revoke <root token>` — a live, unrevoked root token
     defeats the point of not holding a standing one. Confirm with
     `bao token lookup <root token>`: permission-denied means it's
     gone.

**This makes `vault-bootstrap` a single point of failure for the
mechanism above**, and worse than the pre-2.6.x world in one specific
way: 2.6.x's authenticated `generate-root-token` endpoint needs a
capable token *in addition to* the Shamir quorum, not the quorum alone.
If `vault-bootstrap` is ever lost, revoked, or its policy corrupted
with nothing else capable around, the Shamir shares alone no longer get
you out - only a full re-init does. Back it up accordingly.

## Re-init runbook

For when OpenBao's raft dataset needs to be discarded and rebuilt from
scratch, see [`openbao-reinit-runbook.md`](openbao-reinit-runbook.md) -
kept as its own doc rather than a section here, since it's a separate,
rare procedure that merely *uses* this AppRole, not part of its
day-to-day behavior.
