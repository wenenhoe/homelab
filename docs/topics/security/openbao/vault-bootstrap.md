# OpenBao's `vault-bootstrap` AppRole

The standing answer to "how does this repo create a new Vault
policy/AppRole, now that the initial root token is revoked." See
[ADR 0025 (Admin without root token)](../../../decisions/0025-admin-capability-without-a-standing-root-token/revision-000.md)
for why this exists instead of a permanent root token or a repeat
re-init every time a new identity is needed.

## What it can and can't do

Policy: [`vault-bootstrap.hcl`](../../../../docker/openbao/policies/vault-bootstrap.hcl) -
`create`/`update` on `sys/policies/acl/*` and `auth/approle/role/*`
only. It cannot read a single application secret (`secret/data/*` is
untouched by its policy), cannot seal/unseal, cannot enable a secrets
engine or auth method, cannot touch `sys/raw`, and does not hold
`sudo` on `sys/generate-root-token/*` as a standing grant.

That said, policy-write is inherently self-escalating in Vault/OpenBao
ACLs - a token that can write policy can always author itself a wider
one. `vault-bootstrap` doesn't eliminate that; it turns "instant
god-mode" into a two-step, audit-logged action (the audit device from
[ADR 0026 (High-value secret read alerts)](../../../decisions/0026-detecting-reads-of-high-value-secrets/revision-000.md)
is live, so a policy edit followed by a login is visible, not silent).
Treat its `secret_id` with the same offline discipline as the Shamir
shares - never a casual `ansible/files/secrets/` entry - since it is,
functionally, this repo's root-recovery mechanism now.

## Where it can log in from

From the day the shell moves there, the role is bound to the operator host
(VM 252, `192.168.25.2`, see
[ADR 0058 (Operator work host)](../../../decisions/0058-where-operator-work-runs/revision-000.md)),
the one machine `openbao_utils.shell` runs from. `secret_id_bound_cidrs`
refuses a `secret_id` presented from any other address, and
`token_bound_cidrs` refuses a token used from one. The `secret_id` itself
never expires (`secret_id_ttl=0`), so it stays valid until it is rotated by
hand, and the bind is what limits where a copy of it is any use.

The role is not created by this repo's automation, so the bind is set by hand
from a `vault-bootstrap` session, after a first login from the operator host
has succeeded ([`operator-host-takeover.md`](../../../projects/operator-host-takeover.md)
lists it as the last step of moving the controller).
A role write on this backend merges into the stored role, so these two fields
are all it needs:

```sh
bao write auth/approle/role/vault-bootstrap \
  secret_id_bound_cidrs="192.168.25.2/32" \
  token_bound_cidrs="192.168.25.2/32"
bao read auth/approle/role/vault-bootstrap
```

`token_bound_cidrs` reads back as the bare address, the same binding
([`openbao-cd-agent-approles.md`](openbao-cd-agent-approles.md) says why).
A session started from any other address is refused after this, including one
from a laptop or from the machine the shell ran on before the move. Rebuild a
lost operator host at the same address; moving the role to another address
needs a login from the old one first, or a re-init
([`reinit-runbook.md`](reinit-runbook.md)).

## Day-to-day use: minting a new AppRole

```sh
# controller: paste alone; it waits for the role_id, then opens a shell and waits for the secret_id
cd tools && read -r -p 'vault-bootstrap role_id: ' rid && python3 -m openbao_utils.shell "$rid"; unset rid
```

Paste `secret_id` when prompted (from the password manager — see
"What it can and can't do" above, never `ansible/files/secrets/`).
Runs from `controller`, fetching step-ca's root cert fresh over SSH
each time (`shell.py`'s own docstring). Drops into an
interactive shell with `BAO_ADDR`/`BAO_CACERT`/
`BAO_TLS_SERVER_NAME`/`BAO_TOKEN` already exported — every command
below is plain native `bao`:

```sh
# inside that shell: paste alone; it waits for the new role's name and limits
read -r -p 'role name: ' role; read -r -p 'token_ttl: ' token_ttl; read -r -p 'token_max_ttl: ' token_max_ttl; read -r -p 'secret_id_ttl: ' secret_id_ttl; read -r -p 'secret_id_num_uses: ' secret_id_num_uses
```

```sh
# same shell
bao policy write "$role" - < "../docker/openbao/policies/$role.hcl"
bao write "auth/approle/role/$role" \
  token_policies="$role" \
  token_ttl="$token_ttl" token_max_ttl="$token_max_ttl" \
  secret_id_ttl="$secret_id_ttl" secret_id_num_uses="$secret_id_num_uses"
bao read "auth/approle/role/$role/role-id"
bao write -f "auth/approle/role/$role/secret-id"
exit   # revokes the vault-bootstrap token
```

The shell starts in `tools/` on `controller`, so the policy is read from
the checkout, where every policy is checked in under
[`docker/openbao/policies/`](../../../../docker/openbao/policies), not
copied to `security`.

Same parameter-choice discipline as `auth.md`'s `controller`
role: pick TTLs/CIDR-binds appropriate to the new identity's own job,
don't copy `controller`'s or `vault-bootstrap`'s own values by default.

## Using this for emergency root access

If a genuine need for full root access ever comes up (not just another
narrow AppRole), `vault-bootstrap` can produce one without a second
re-init - the same self-escalation property above, deliberately used
on purpose this one time:

1. Log in with `vault-bootstrap`, as under
   [Day-to-day use](#day-to-day-use-minting-a-new-approle) —
   the spawned shell is fully interactive, so step 4's unseal-key
   submissions need no special handling.
2. `bao policy write vault-bootstrap-emergency -`: a copy of
   `vault-bootstrap.hcl` plus one added stanza:
   `path "sys/generate-root-token/*" { capabilities = ["sudo", "create", "read", "update", "delete"] }`.
   `read` and `delete` are both required, not just `sudo`/`create`/
   `update` — `-generate-otp`'s status check and `-cancel` 403 without
   them, confirmed live.
3. `bao write auth/approle/role/vault-bootstrap token_policies="vault-bootstrap-emergency"`,
   then exit and log in again
   (same `shell.py` command as step 1) — a token's policies are
   fixed at login time, so the updated role only takes effect on the
   next login. AppRole role writes on this backend merge into the
   stored role rather than replacing it — `pathRoleCreateUpdate` loads
   the existing role first and only overwrites fields present in the
   request (confirmed from `path_role.go`/`tokenutil.go`), so a field
   left off this command keeps its current stored value. Re-supplying
   every field anyway is still worth doing for an explicit audit
   trail, just not required to avoid data loss.
4. Start the generation, with the one-time password held in a variable:

   ```sh
   # inside that shell
   otp=$(bao operator generate-root -generate-otp)
   bao operator generate-root -init -otp="$otp"
   ```

   It prints a `Nonce`. Submit the Shamir keys one at a time, up to the
   threshold (`-status` shows progress without consuming a key). With no key
   argument, `bao` prompts for it:

   ```sh
   # paste alone; it waits for the nonce
   read -r -p 'nonce: ' nonce
   ```

   ```sh
   # once per key: paste alone; it waits for one unseal key, hidden
   bao operator generate-root -nonce="$nonce"
   ```

   The final submission prints an `Encoded Token`. Decode it from stdin into a
   variable, so the root token is never printed:

   ```sh
   # paste alone; it waits for the encoded token
   read -rs -p 'encoded token: ' encoded; echo
   ```

   ```sh
   root=$(printf '%s' "$encoded" | bao operator generate-root -decode=- -otp="$otp")
   unset encoded
   ```

   `-otp` has no stdin form, so the one-time password is an argument; without
   the encoded token it decodes nothing.
5. Use the root token for whatever the actual emergency need is, passed as
   `BAO_TOKEN="$root" bao ...`.
6. Revert — three things, not one:
   - Rebind `vault-bootstrap` back to `token_policies="vault-bootstrap"`.
   - `bao policy delete vault-bootstrap-emergency` — deleting the
     role's reference to it isn't enough; the policy object itself
     stays unless removed, sitting unattached and unused, which is
     exactly the kind of "slower-to-notice god-mode" this design
     exists to avoid.
   - Revoke the root token and confirm it is gone: a live, unrevoked root token
     defeats the point of not holding a standing one. The lookup must answer
     permission denied.

     ```sh
     BAO_TOKEN="$root" bao token revoke -self
     BAO_TOKEN="$root" bao token lookup
     unset root otp
     ```

**This makes `vault-bootstrap` a single point of failure.** Since 2.6.x the
`generate-root-token` endpoint needs a capable token *as well as* the Shamir quorum. If
`vault-bootstrap` is lost, revoked or its policy corrupted with nothing else capable, the shares
alone no longer get you out; only a re-init does. Back it up accordingly.

## Re-init runbook

For when OpenBao's raft dataset needs to be discarded and rebuilt from
scratch, see [`reinit-runbook.md`](reinit-runbook.md) -
kept as its own doc rather than a section here, since it's a separate,
rare procedure that merely *uses* this AppRole, not part of its
day-to-day behavior.
