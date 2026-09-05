# 0019. Move Cloudflare R2's admin token into OpenBao

**Status:** Proposed

## Context

[0002](0002-r2-rotation-token-accepted-as-master-equivalent.md)
established that R2's cached admin token is master-equivalent for
blast-radius purposes and can't be narrowed — Cloudflare's tokens API
rejects granting `API Tokens Write` to any token created via the API
itself, so `create_rotation_keys.py --provider r2 --rotate` has never
minted anything; it only caches (or re-caches) a token a human creates
directly in the Console. The open question was always whether moving
it into Vault was worth doing given that limitation — worth it once a
real automated consumer exists to justify the tighter access control
Vault provides, not worth it for storage-location's own sake.

[0018](0018-openbao-repoint-not-native-plugin.md) now puts every other
credential's rotation on a schedule, run by the `cd_agent` host
([0020](0020-pull-based-cd-agent-not-self-hosted-github-runner.md)).
Leaving R2's token as the one credential still living in
`ansible/files/secrets/` would mean `cd_agent` needs direct filesystem
access to that flat-file cache just for this one provider, reintroducing
the exact exposure this migration removes for the other 9 credentials.

R2 stays a structural exception even once it's in Vault, though:
moving the token doesn't change what [0002](0002-r2-rotation-token-accepted-as-master-equivalent.md)
already established — Cloudflare's API can automate *caching* R2's
rotation token, never *minting* its replacement.

## Decision

Move the R2 admin token into OpenBao KV v2 during the migration
roadmap's cloud-credential migration stage, alongside the other 8
credentials. Scope it to one Vault path, readable only by a
policy attached to `cd_agent`'s rotation-job AppRole specifically — not
shared with `cd_agent`'s deploy-job AppRole or `controller`'s own — and
alert on every read of that path, not just on its expiry.

Because minting isn't automatable for this provider, the 90-day
master-rotation cadence [0018](0018-openbao-repoint-not-native-plugin.md)
introduces runs differently here than for B2/OCI: the job checks
whether the cached token's `expires_on` (already tracked per
[0015](0015-credential-expiry-native-where-possible-self-tracked-where-not.md))
is inside the rotation window and, if so, alerts that a human needs to
create a new Console token — the same `check_freshness.py`-style
alerting this repo already does, not a mint-verify-revoke pipeline.
Once a human creates and pastes the new token, the job's only automated
part is caching it into Vault and verifying it authenticates, mirroring
what `create_rotation_keys --provider r2 --rotate` already does against
a local cache file today.

## Consequences

- Blast radius is unchanged from [0002](0002-r2-rotation-token-accepted-as-master-equivalent.md)'s
  original finding — full Cloudflare account access if it leaks,
  regardless of where it's stored. This decision changes who/what can
  reach the token, not what it can do once reached.
- After the roadmap's cutover stage, all 9 original credentials plus
  this one live in Vault — no flat-file exception remains.
- The per-read alert is new work: no existing consumer in
  `ansible/cloud_credentials/` alerts on access rather than on expiry.
  Vault's own audit log is the natural source for it (an
  audit-log-triggered alert, not a `check_freshness.py`-style poll,
  since a read-alert needs to fire per access) — the exact mechanism
  is a build detail for the cloud-credential migration stage, not
  decided here.
- R2's 90-day cycle can't be fully unattended the way B2's/OCI's can —
  a human creating a Console token every 90 days remains a hard
  requirement, not an implementation detail automation will eventually
  absorb.
