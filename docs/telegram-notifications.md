# Telegram Notifications

One bot, one group chat with [Topics](https://telegram.org/blog/topics-in-groups-collectible-usernames)
enabled, a different topic per concern. Six consumers today: two share
the Backups topic since they're the two halves of the same
disaster-recovery story (see [`disaster-recovery.md`](disaster-recovery.md)),
and two share the Certs topic since they're both certificate-lifecycle
alerts, just for different certs:

| Concern | Sends via | Topic var |
| :--- | :--- | :--- |
| Image updates (diun) | diun's own Telegram notifier | `telegram_chatid_updates` |
| Host/container monitoring (Beszel) | Beszel's built-in notifications | `telegram_chatid_monitoring` |
| Backup job failures | `docker-volume-backup`'s notifier | `telegram_chatid_backups` |
| Cloud-sync relay failures | `telegram-notify-cloud-sync` (systemd) | `telegram_chat_id` / `telegram_topic_id_backups` |
| Cert renewal failures (lldap) | `telegram-notify@` (systemd) | `telegram_chat_id` / `telegram_topic_id_certs` |
| Caddy cert-expiry check failures | `telegram-notify-cert-expiry` (systemd) | `telegram_chat_id` / `telegram_topic_id_certs` |

## One-time Telegram-side setup

1. Create the bot via [@BotFather](https://t.me/BotFather); save the token.
2. Create (or pick) a group, enable **Topics** in its settings, add the bot
   as an **admin** — a non-admin bot can't post into an arbitrary topic.
3. Create a topic per row above (e.g. "Updates", "Monitoring", "Backups",
   "Certs").
4. Get the chat ID: forward any message from the group to
   [@shoutrrrbot](https://t.me/shoutrrrbot), or address a message to
   `@shoutrrrbot` from inside the group.
5. Get each topic's ID: open the topic in Telegram, copy a message link
   (`https://t.me/c/<chat>/<topic_id>/<msg_id>`) — the middle number is
   the topic (thread) ID.

## Wiring it into this repo

`telegram_token`/`telegram_chat_id` are the shared bot secrets
(`secrets_registry.yaml`, see [`secrets.md`](secrets.md)). Each concern
above has its own `telegram-topic-id-*` entry, `allow_blank: true` since
Topics is optional — a blank topic ID falls back to posting in the
group's main stream, no code change needed either way (see `main.yaml`'s
`telegram_chatid_*` vars). Bootstrap them the same way as any other
manual secret:

```sh
printf '%s' '<topic-id>' > ansible/files/secrets/telegram-topic-id-updates
```

**Two different address formats, on purpose**: diun, `docker-volume-backup`,
and Beszel all go through [shoutrrr](https://containrrr.dev/shoutrrr/v0.8/services/telegram/)
(or diun's own equivalent), whose convenience syntax is a single
`chat_id:topic_id` string — that's what `telegram_chatid_*` produces. The
three systemd-based notifiers below call Telegram's Bot API directly
instead, and the real API takes `chat_id` and `message_thread_id` as two
separate parameters — it does **not** understand the colon-combined
form. That's why the raw, un-prefixed `telegram_topic_id_*` vars exist
alongside `telegram_chatid_*`.

**The systemd-based notifiers share one library role**, `telegram_notify`
(`ansible/roles/telegram_notify`) — a plain oneshot unit that curls
`sendMessage` directly, parameterized by unit name, description, message
text, and which topic to post to. It's included via `include_role` from
each consumer's own `tasks/main.yaml`, has no `tasks/main.yaml` or
molecule suite of its own (same shape as `molecule_helpers`), and never
reloads systemd or notifies a handler itself — the including role does
that off the `telegram_notify_env_result`/`telegram_notify_service_result`
it registers, so the shared role never depends on a same-named handler
existing in whatever play includes it. `telegram-notify@` and
`telegram-notify-cloud-sync` predate this role and aren't migrated onto
it yet — see the per-app notes below.

**The bot token's own colon is load-bearing.** A real token from
BotFather is already shaped `<bot-id>:<rest>` — shoutrrr's Telegram
service relies on that exact colon to split the URL's userinfo into
`chat_id`/`message_thread_id`-style username/password parts, then
re-joins and validates them against `^[0-9]+:[a-zA-Z0-9_-]+$`. Any token
missing that shape fails sender setup on every single scheduled run —
not just notification delivery — which for `docker-volume-backup`
specifically means the backup itself never runs either, since sender
setup happens before the backup logic, not after. `telegram_token` here
is always your bot's real token, so this only bites test fixtures using
a placeholder that isn't shaped like one.

## Per-app notes

- **diun**: `docker/diun/configs/env.j2` — `TELEGRAM_CHAT_ID` is
  `telegram_chatid_updates`.
- **Beszel**: not Ansible-managed — its notification channels live in the
  hub's own database, configured once by hand in Settings > Notifications
  (same category as the hub key/token bootstrap, see
  [`beszel.md`](beszel.md#connection-model)). Add a service URL of
  `telegram://<telegram_token>@telegram?chats=<telegram_chatid_monitoring>`.
- **backup_agent**: `NOTIFICATION_URLS` in the role's shared `.env`
  (`ansible/roles/backup_agent/templates/env.j2`) — fires on failed
  backup runs only (`docker-volume-backup`'s own default
  `NOTIFICATION_LEVEL=error`), not on every successful one.
- **cloud_sync**: `ansible/roles/cloud_sync/templates/cloud-sync.service.j2`
  sets `OnFailure=telegram-notify-cloud-sync.service`, its own plain
  (non-templated) unit — posts to the same Backups topic as
  backup_agent above, since it's the "relay it onward" half of the same
  disaster-recovery story (see
  [`disaster-recovery.md`](disaster-recovery.md)). Not shared with
  `cert-renewer@`'s notifier below despite the near-identical shape:
  the two run on different hosts (storage vs security), so there's
  nothing to actually share on disk — each role owns its own copy.
- **Cert renewal**: `ansible/roles/lldap_cert/templates/cert-renewer@.service.j2`
  sets `OnFailure=telegram-notify@%i.service`, a generic systemd
  instantiated unit (`telegram-notify@.service.j2`, same role) that curls
  Telegram's `sendMessage` directly using `/etc/telegram-notify/env`
  (rendered by the role, `no_log: true`). `%i` here is the *invoking*
  unit's own instance (e.g. `lldap`), not a generic failed-unit name —
  this template is coupled to `cert-renewer@`'s naming, not a catch-all
  notifier for arbitrary units. An `ExecCondition` skip (the common,
  nothing-due-for-renewal case) is not a failure and never triggers this
  — systemd only treats exit codes 255 or an abnormal exit as a failure
  for `ExecCondition`.
- **Caddy cert-expiry**: `ansible/roles/caddy_cert_expiry` — a daily
  timer runs `check.sh`, which checks the certificate Caddy is actually
  serving (a live TLS handshake against one of this host's own routed
  subdomains, not a file on disk) rather than renewal internals, since
  Caddy manages its own ACME renewal and this is meant to catch that
  process silently failing. One check per host: `caddy_domain` and its
  wildcard cert are both per-host, so every routed subdomain shares the
  same cert — no per-domain enumeration needed.
  `OnFailure=telegram-notify-cert-expiry.service`, its own consumer of
  the shared `telegram_notify` role above, posting to the same Certs
  topic as `cert-renewer@` since it's the same kind of concern for a
  different cert. Threshold is `caddy_cert_expiry_threshold_days`
  (default 30).

## Verifying it actually delivers

Molecule (`ansible/roles/lldap_cert/molecule/default`,
`ansible/roles/cloud_sync/molecule/default`, and
`ansible/roles/caddy_cert_expiry/molecule/default`) confirms the
`OnFailure=` link exists, the unit templates correctly, and it loads and
runs under real systemd — it can't confirm a real Telegram message
arrives, since CI has no live bot credentials. Check that part yourself
after deploying:

```sh
# On the security host — force the cert-renewal alert to fire
sudo systemctl start telegram-notify@lldap.service
journalctl -u telegram-notify@lldap.service --no-pager -n 20

# On the storage host — force the cloud-sync alert to fire
sudo systemctl start telegram-notify-cloud-sync.service
journalctl -u telegram-notify-cloud-sync.service --no-pager -n 20

# On any host — force the cert-expiry alert to fire
sudo systemctl start telegram-notify-cert-expiry.service
journalctl -u telegram-notify-cert-expiry.service --no-pager -n 20
```

A `curl` exit status other than a clean `0` there (bad token, wrong chat
ID, bot not an admin in the topic's group) means the alert wouldn't have
reached you for a real failure either — worth confirming once per host,
not just trusting the config rendered.
