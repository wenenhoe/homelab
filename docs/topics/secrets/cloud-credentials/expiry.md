# Cloud Credential Expiry — R2/B2/OCI

How the 9 cloud credentials expire and how `check_freshness.py` warns before they do: the 90-day lifetime, the weekly check, the Telegram warning ladder and the systemd timer. Creation is in [`creation.md`](creation.md); rotation is in [`rotation.md`](rotation.md).

## Credential expiry

All 9 credentials (6 leaf, 3 rotation) expire after 90 days now — see
[ADR 0015](../../../decisions/0015-cloud-credential-expiry/revision-000.md)
for B2/R2's native provider-side expiry, and
[ADR 0016](../../../decisions/0016-oci-credential-creation-and-expiry/revision-000.md)
for OCI's leaf keys, which are native too now (via SCIM `expiresOn`) —
only OCI's rotation credential (the Confidential Application's client
secret) stays self-tracked, since that specific resource has no native
expiry field of its own. Neither `create_leaf_keys.py` nor
`create_rotation_keys.py` needs a new flag for this — expiry is set
unconditionally on every create/rotate call, the same way capabilities
already are.

**B2** and **R2** enforce this themselves; an expired key/token simply
stops authenticating provider-side. **OCI's leaf keys** do too now,
via SCIM's native `expiresOn`. **OCI's rotation credential** doesn't —
the `App` resource has no expiry field on its client secret at all
(confirmed against Oracle's own SDK model), so a self-tracked
`_rotation-key-oci-created-at` cache file is advisory only, same as
every self-tracked credential in this repo. Nothing currently enforces
it beyond `check_freshness.py`'s own alert.

**R2's rotation admin token** is human-created in the Console (see [its
section](scoping.md#cloudflare-r2--rotation-key-exists-now-but-its-not-scoped-like-the-other-two)) — set an expiration date on it there when you create
it; this script has no way to set one after the fact.

**`check_freshness.py`** reads all 9 back — natively for B2
(`b2_list_keys`), R2 (`GET .../tokens/{id}` for the leaf tokens,
`GET /user/tokens/verify` for the rotation token — see below), and
OCI's leaf keys (`IdentityDomainsClient.get_customer_secret_key`, SCIM's `GET /admin/v1/CustomerSecretKeys/{id}`) —
from the self-tracked cache file for OCI's rotation credential only —
and reports each as fresh, expiring soon (within `expiry.WARNING_DAYS`,
30 days), expiring very soon (within `expiry.URGENT_DAYS`, 14 days),
past its window, or check-failed (couldn't be read at all — bad auth,
missing cache file, HTTP error). Only the last of those fails the
run's own exit code — `systemctl --user status` reflects whether the
check itself is healthy, not whether a credential happens to be due.

**The R2 rotation token is checked via `GET /user/tokens/verify`, not
any `/accounts/{account_id}/tokens` endpoint:** this admin token is a
Cloudflare **User API Token**, created via *My Profile > API Tokens*
exactly as `leaf_keys/r2.py`'s own prompt instructs — a different
resource category from "Account Owned API Tokens"
(`/accounts/{account_id}/tokens/*`, what the leaf tokens actually are,
since those *are* created via that API). Confirmed by directly
comparing all four combinations against a real token:
`GET /user/tokens/verify` succeeded (200, valid and active);
`GET /accounts/{account_id}/tokens/verify` and
`GET /accounts/{account_id}/tokens` (List) both only ever operate on
the Account-owned category and never see a User token no matter how
they're queried. `/user/tokens/verify` needs no `account_id` at all:
it verifies whichever token authenticated the request, scoped to the
calling user, not a specific account.

Any non-fresh result posts a Telegram alert to the `Backups` topic
(same one `telegram-notify-cloud-sync` already uses — see
[`telegram-notifications.md`](../../monitoring/telegram-notifications.md)), using the
same `telegram-token`/`telegram-chat-id` every other consumer in this
repo reads from Vault (`secret/data/hosts/all/telegram/*`, per
[ADR 0021](../../../decisions/0021-secret-path-layout-for-secrets-with-no-host-owner/revision-000.md)).
Not routed through the
`telegram_notify` Ansible role — that's templated and deployed to
`managed_hosts`, and `controller` deliberately isn't one — so this
calls Telegram's `sendMessage` directly instead, same request shape.
No alert on an all-fresh run.

**This call uses `parse_mode=HTML`, not the legacy Markdown mode
`telegram_notify` and every other consumer in this repo use.**
Legacy Markdown requires escaping `` ` ``/`_`/`*`/`[` when literal, but
also forbids escaping inside an already-open entity (Telegram's own
documented rule) — a message composed by wrapping a bold header around
text containing one of those characters can't be made safe by
escaping alone. `detail` strings here embed arbitrary provider error
text and URLs, so that combination isn't a corner case, it's routine.
HTML has no equivalent trap: a `<b>` tag is either well-formed or it
isn't, and `_`/`*`/`` ` ``/`[` are always ordinary characters inside
or outside one. Only `&`, `<`, `>` are ever special; `_escape_telegram_html`
covers exactly those three, applied to `detail`.
`telegram-notifications.md` itself still documents the Markdown
convention correctly — accurate for `telegram_notify`'s own
static-template callers, which is all it ever claimed to cover.

The 30/14-day warning ladder exists specifically because B2 and R2
enforce their own expiry server-side: by the time either goes fully
stale, the credential has already stopped authenticating and
`cloud_sync` is already broken. A single threshold would still buy
lead time, but two grades of urgency (heads-up at a month out, urgent
at two weeks) means the reminder actually escalates as the deadline
gets closer instead of one flat repeated ping — see ADR 0015 for why
past-window alone wasn't enough.

```sh
cd tools
python3 -m cloud_credentials.check_freshness
```

Runs unattended via a systemd **user** timer on `controller` — the
operator's own machine, where the cache already lives (see
`docs/architecture/system-overview.md`) — not through any Ansible role,
since `cloud_credentials` isn't one and doesn't deploy to any
`managed_hosts` entry. Install once, by hand:

```sh
cd tools/cloud_credentials/systemd
# Edit check-freshness.service's WorkingDirectory to this clone's actual path first.
mkdir -p ~/.config/systemd/user
cp check-freshness.service check-freshness.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now check-freshness.timer
```

`Persistent=true` on the timer catches up on a missed weekly run once
the machine's next on — see ADR 0015's Consequences for the real limit
this still has on a machine that's off for longer than that.
