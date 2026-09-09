# OpenBao's `vault-bootstrap` AppRole

The standing answer to "how does this repo create a new Vault
policy/AppRole, now that the initial root token is revoked." See
[ADR 0027](decisions/0027-openbao-reinit-with-standing-vault-bootstrap-role.md)
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
ssh security
export BAO_TOKEN=<vault-bootstrap secret_id login token>
alias bao='docker exec -i -e BAO_TOKEN -e BAO_SKIP_VERIFY=true openbao bao'

bao policy write <new-role-name> - < /tmp/<new-role-name>.hcl
bao write auth/approle/role/<new-role-name> \
  token_policies="<new-role-name>" \
  token_ttl=<...> token_max_ttl=<...> \
  secret_id_ttl=<...> secret_id_num_uses=<...>
bao read auth/approle/role/<new-role-name>/role-id
bao write -f auth/approle/role/<new-role-name>/secret-id
```

Same parameter-choice discipline as `openbao-auth.md`'s `controller`
role: pick TTLs/CIDR-binds appropriate to the new identity's own job,
don't copy `controller`'s or `vault-bootstrap`'s own values by default.

## Using this for emergency root access

If a genuine need for full root access ever comes up (not just another
narrow AppRole), `vault-bootstrap` can produce one without a second
re-init - the same self-escalation property above, deliberately used
on purpose this one time:

1. Log in with `vault-bootstrap`.
2. `bao policy write vault-bootstrap-emergency -` a copy of
   `vault-bootstrap.hcl` plus one added stanza:
   `path "sys/generate-root-token/*" { capabilities = ["sudo", "create", "update"] }`.
3. `bao write auth/approle/role/vault-bootstrap` (or a fresh short-lived
   role) `token_policies="vault-bootstrap-emergency"`, log in again.
4. `bao operator generate-root -init`, then supply the Shamir quorum
   from the break-glass bundle - the login token above satisfies 2.6.x's
   authenticated-endpoint requirement, the Shamir shares satisfy the
   quorum. Confirm the exact `-init`/`-otp`/`-decode` sequence against
   `bao operator generate-root -h` on the real running version before
   relying on it live - not re-derived here from memory.
5. Revert the policy to plain `vault-bootstrap.hcl` (remove the
   `sys/generate-root-token/*` stanza) once done - the added capability
   is for the duration of one recovery, not a standing grant.

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
