# 0006. `cloud_sync` uses rclone `copy`, never `sync`

**Status:** Accepted

## Context

`cloud_sync` (`storage`-only) relays already-encrypted backup archives
from SeaweedFS onward to R2/B2/OCI. The relay needs some way to move
new objects outward — the question is whether that mechanism can also
propagate deletions.

SeaweedFS's own native remote-sync tooling (`weed filer.remote.gateway`)
was checked first and ruled out: its own docs state that local
deletions propagate to the remote. That's exactly the failure mode
this design needs to avoid — see
[`disaster-recovery.md`](../disaster-recovery.md#threat-model)'s threat
model: a compromised on-prem host shouldn't be able to reach into the
offsite copy at all, and a mechanism that mirrors deletions gives it
exactly that reach through the relay, even without a direct cloud
credential.

## Decision

Use rclone `copy`, never `sync`, for every relay from SeaweedFS to a
cloud target. `copy` only ever adds objects on the destination side.

Cloud-side retention (the immutable-window and delete-after settings
per provider) is likewise kept as a provider-native lifecycle rule
configured once, out-of-band in each provider's own console — not
managed by this repo at all. A homelab-side retention job would need
delete access to enforce it, which is the one capability this design
goes out of its way to avoid granting to anything running on-prem.

## Consequences

Nothing running on `storage`, or any compromised app host upstream of
it, can delete or overwrite an object that's already landed in the
cloud — even with `cloud_sync`'s own credentials fully compromised.
This is the actual mechanism (not IAM narrowing) that gives the
offsite copies their compromise-resistance; see
[ADR 0002](0002-r2-rotation-token-accepted-as-master-equivalent.md)
for where that matters most (R2, where credential scoping alone can't
carry the same guarantee).

The trade-off: objects can only ever accumulate. There's no
automated cleanup of orphaned/superseded objects from this repo's
side — that's what the provider-native lifecycle rules above are for,
configured and audited separately from anything this repo controls.
