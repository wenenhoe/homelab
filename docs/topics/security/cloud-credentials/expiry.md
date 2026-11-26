# Cloud Credential Expiry — R2/B2/OCI

How the cloud credentials expire and how `check_credential_expiry.py` warns before they do: the 90-day lifetime, the weekly check, the Telegram warning ladder and the systemd timer. Creation is in [`creation.md`](creation.md); rotation is in [`rotation.md`](rotation.md).

## Credential expiry

Every credential, leaf and rotation, expires after 90 days
([ADR 0109 (Cloud credential expiry)](../../../decisions/0109-knowing-a-cloud-credential-is-about-to-expire/revision-000.md)).
Every create and rotate call sets it; no flag is needed.

| Credential | Enforced by | Read back with |
| :--- | :--- | :--- |
| B2 keys | The provider: an expired key stops authenticating | `b2_list_keys` |
| R2 leaf tokens | The provider | `GET .../tokens/{id}` |
| R2 rotation token | The provider, on the date you set when you [create it](scoping.md#cloudflare-r2--rotation-key-exists-now-but-its-not-scoped-like-the-other-two) in the console. The script cannot set it afterwards | `GET /user/tokens/verify` |
| OCI leaf keys | The provider, through SCIM's `expiresOn` | `GET /admin/v1/CustomerSecretKeys/{id}` |
| OCI rotation client secret | Nobody: the `App` resource has no expiry field | The self-tracked `_rotation-key-oci-created-at` file, advisory only |

## Expiry check

```sh
cd tools && python3 -m cloud_credentials.check_credential_expiry
```

| Reported as | When | Telegram | Exit |
| :--- | :--- | :--- | :--- |
| fresh | More than `WARNING_DAYS` (30) left | None | 0 |
| expiring soon | Within `WARNING_DAYS` | Alert | 0 |
| expiring very soon | Within `URGENT_DAYS` (14) | Alert | 0 |
| past its window | Expired | Alert | 0 |
| check failed | Bad auth, missing cache file or HTTP error | Alert | 1 |

The exit status says whether the check is healthy, not whether a credential is due, so
`systemctl --user status` does not flag ordinary expiry. The two warning grades exist
because B2 and R2 enforce expiry themselves: by the time a credential is past its window,
`cloud_sync` is already broken.

Besides the cloud-sync leaves, it covers the OpenBao snapshot write keys and the Tofu state
keys, each looked up by the key ID the leaf tier holds, which names the key to the provider
and authenticates nothing. The Tofu secrets stay in files on the host that runs Tofu
([`state-and-credentials.md`](../../infra/tofu/state-and-credentials.md)). The break-glass
snapshot read key has no expiry and is not checked.

**The R2 rotation token needs `GET /user/tokens/verify`.** It is a Cloudflare *User API
Token* (made under *My Profile > API Tokens*), a different category from the
*Account Owned API Tokens* the leaf tokens are. The
`/accounts/{account_id}/tokens` endpoints, verify and list alike, never see a User token.
`/user/tokens/verify` takes no account ID and verifies whichever token authenticated.

## Alerts

Any non-fresh result posts to the `Backups` topic (as `telegram-notify-cloud-sync` does,
[`telegram-notifications.md`](../../monitoring/telegram-notifications.md)), with the
`telegram-token` and `telegram-chat-id` every consumer reads from OpenBao
([ADR 0021 (Ownerless secret paths)](../../../decisions/0021-secret-path-layout-for-secrets-with-no-host-owner/revision-000.md)).
It calls `sendMessage` directly, since the `telegram_notify` role deploys only to
`managed_hosts` and `controller` is not one. An all-fresh run posts nothing.

**It uses `parse_mode=HTML`**, unlike every other sender here. Legacy Markdown forbids
escaping inside an open entity, so a bold header around arbitrary provider error text and
URLs cannot be made safe. In HTML only `&`, `<` and `>` are special, and
`_escape_telegram_html` escapes those three in `detail`.

## Scheduling

It runs weekly on a systemd **user** timer on `controller`, the operator's machine where the
cache lives (`docs/architecture/system-overview.md`), not through an Ansible role. The CD
agent also runs it weekly as its `credential-expiry` job
([`cd-agent-host.md`](../../deploy/cd-agent-host.md)). Install once:

```sh
# from the repo root, after `uv sync` (the unit uses the clone's .venv)
mkdir -p ~/.config/systemd/user
sed "s|CHANGE-ME-path-to-this-repo|$PWD|" tools/cloud_credentials/systemd/check-freshness.service \
  > ~/.config/systemd/user/check-freshness.service
cp tools/cloud_credentials/systemd/check-freshness.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now check-freshness.timer
```

Then run it once, since a unit that cannot start only shows as failed in its status:

```sh
systemctl --user start check-freshness.service
journalctl --user -u check-freshness.service -n 15 --no-pager
```

A repo moved to another path, or a rename of the module the unit runs, needs the same `sed` again. A failed run raises no
alert on `controller`, so check `systemctl --user status check-freshness.service`
after an install or a move.

`Persistent=true` on the timer catches up on a missed weekly run once
the machine's next on — see ADR 0109's Consequences for the real limit
this still has on a machine that's off for longer than that.
