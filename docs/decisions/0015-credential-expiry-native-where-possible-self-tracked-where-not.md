# 0015. Native expiry where providers offer it, self-tracked timestamps where they don't, checked by a controller-hosted timer

**Status:** Accepted

## Context

None of the 6 leaf credentials or 3 rotation keys/tokens `cloud_credentials`
creates ever expired. Closing that gap meant answering, per provider,
whether an expiry could be set at creation time and read back later, or
whether this repo would have to track it itself.

**B2** already documents `validDurationInSeconds` on `b2_create_key`
(confirmed against Backblaze's own reference: a positive integer under
1000 days, after which the response carries `expirationTimestamp`) —
native, and queryable later via `b2_list_keys`.

**OCI** looked like it might have the same via Identity Domains'
Customer Secret Key resource, which does have a real `expiresOn` field
— but that field lives on a different resource entirely
(`oci.identity_domains.models.CustomerSecretKey`, reachable only
through the Identity Domain's own SCIM endpoint), not on the classic
`/20160918/users/{id}/customerSecretKeys` endpoint this repo actually
calls. Confirmed against Oracle's own SDK model for that endpoint's
request body: `CreateCustomerSecretKeyDetails` has exactly one
attribute, `display_name`. Confirmed live too
(`cloud_credentials/spikes/oci_scim_auth_check.py`): the rotation
identity's `OCISigner` gets `401 error.common.common.accessDenied`
from the SCIM endpoint — rejected outright, not under-permissioned.
Identity Domains authenticates SCIM calls via OAuth2 client-credentials
from a registered Confidential Application (per Oracle's own Identity
Domains REST API docs), an unrelated model to the request-signing used
everywhere else in this repo. A SCIM migration is a second auth
integration on a second resource model, not an extension of the
existing one. Out of scope for this thread.

**R2** turned out better than assumed going in: `POST
/accounts/{account_id}/tokens` (the exact call `r2_create_leaf_token`
already makes) accepts an optional `expires_on`, confirmed against
Cloudflare's own Create Token reference. `GET
/accounts/{account_id}/tokens/{token_id}` reads it back later without
needing the token itself — the rotation admin token's existing `Account
API Tokens Edit` permission is enough to call it for the leaf tokens it
created. The rotation admin token is a human-created Console token
(see [0002](0002-r2-rotation-token-accepted-as-master-equivalent.md)),
so it can carry an expiration too, set by hand at creation, and
`check_freshness.py` reads that back live the same way — see
`cloud-credential-creation.md`'s Credential expiry section for exactly
which endpoint that requires and why (it changed once already, after
this ADR was first written — don't restate the specific endpoint here
a second time).

That leaves a genuine three-way split: B2 and R2 are natively
expirable *and* natively queryable, so neither needs a cache file
tracking anything. OCI has no expiry concept in its classic Identity
API at all — not lenient defaults, not something to opt into — so a
self-tracked `-created-at` cache file, written at the same moment as
the credential's other cache files, is the only option.

A check still needs to run somewhere, unattended, and alert on a
credential past its window — but `cloud_credentials` isn't an Ansible
role and doesn't deploy to any `managed_hosts` entry. Its cache lives
under `ansible/files/secrets/` on the `controller` host only (the
operator's own machine — see `docs/architecture/system-overview.md`),
so that's the only place a check can read it without syncing secret
material or self-tracked timestamps anywhere new.

## Decision

- B2 and R2: set native expiry at creation (`validDurationInSeconds`,
  `expires_on`), leaf credentials and rotation keys/tokens alike. No
  cache file added for either.
- OCI: write a companion `<credential>-created-at` cache file
  alongside each credential's existing cache files, for both leaf
  credentials and the rotation keypair.
- `check_freshness.py` queries B2/R2 live and reads OCI's self-tracked
  timestamps, classifying each as fresh, expiring within
  `expiry.WARNING_DAYS` (30 days), expiring within `expiry.URGENT_DAYS`
  (14 days), past its window, or check-failed — a genuine check
  failure is the only thing that fails the run's own exit code; any
  other non-fresh result posts a Telegram alert (to the `Backups`
  topic, same secrets every other consumer in this repo already reads
  from `ansible/files/secrets/`) instead of just sitting in the
  journal. A plain fresh/past-window split was tried first and
  dropped: B2/R2 enforce their own expiry server-side, so "past its
  window" for either means `cloud_sync` is already broken by the time
  anyone would see it. Two warning grades, not one, so the reminder
  escalates as the deadline approaches instead of a single flat ping
  repeated every run for a month.
- Installed as a systemd **user** timer on `controller`, not as an
  Ansible role or a unit deployed to any managed host — plain files
  under `ansible/cloud_credentials/systemd/`, installed by hand once
  (same one-time, human-attended nature as bootstrapping a rotation
  key in the first place).

## Consequences

- All 9 credentials now expire on a 90-day (quarterly) window, whether
  that's enforced by the provider (B2, R2) or by this check alone
  (OCI). An OCI credential past its self-tracked window keeps working
  provider-side until someone rotates it — the check is advisory, not
  an enforcement mechanism, unlike B2/R2 where the provider itself
  will reject an expired credential.
- The rotation keys/tokens now expire too, including B2's and R2's,
  which authenticate `create_leaf_keys.py` itself. An expired rotation
  credential breaks routine leaf rotation until a human re-runs
  `create_rotation_keys` (B2/OCI) or pastes a new Console token (R2) —
  the same low-frequency, human-attended action
  `cloud-credential-creation.md`'s Rotation section already describes,
  just now with a hard deadline instead of an open-ended one.
- The freshness check depends on `controller` actually running its
  timer, which depends on the operator's own machine being on often
  enough for a weekly, `Persistent=true` timer to catch up. This is a
  real gap on a machine that's off for a long stretch, not a
  hypothetical one — there is no fallback host this could deploy to
  without giving some managed host read access to
  `ansible/files/secrets/`, which is a materially different security
  posture and not something this decision takes on silently.
- OCI's gap noted in `cloud-credential-creation.md` — no confirmed
  policy condition scoping `manage users` to one named resource —
  remains open and unrelated to this change.
- If `telegram-token`/`telegram-chat-id` aren't cached, an alert is
  silently downgraded to a journal line instead of failing the run —
  consistent with check failures being the only thing that fails
  `check_freshness.py` itself, but it does mean a missing Telegram
  secret produces no visible symptom beyond a log line nobody's
  otherwise watching.

See
[`cloud-credential-creation.md`](../cloud-credential-creation.md#credential-expiry)
for the setup/verification steps this decision produced.
